# infra

Configuration for the shared Hetzner server that runs my hobby projects' APIs and their Postgres databases. The first project is life-app (`lakaniemi/life-app`).

## Decisions

- **Server:** Hetzner Cloud **CPX12** (1 vCPU, 2 GB RAM, 40 GB NVMe) in **HEL1** (Helsinki). €11.99/month before VAT (€15.05 with Finnish VAT), plus €0.50/month before VAT for the IPv4 address. Ubuntu 24.04 LTS. Upgrade the server type when projects need more.
- **IPv4 and IPv6 are both enabled.**
  - IPv4-only client networks couldn't reach the server without IPv4.
  - `github.com` and `ghcr.io` have no IPv6 addresses, so the server couldn't pull images without IPv4.
- **DNS:** every service has its own hostname on `lakaniemi.com`, named after the project, e.g. `life-app-api.lakaniemi.com`. No project gets a generic name like `api.`. Each hostname has A and AAAA records. Apps never use an IP, so moving servers is a DNS change, never an app update.
  - The zone is hosted on Hetzner DNS and managed by Ansible (`hetzner.hcloud` `zone` and `zone_rrset`), so records live in the repo and the service records follow the server's IPs automatically.
  - The domain is registered at Namecheap, whose only role is pointing the nameservers at Hetzner.
  - The zone started fresh: nothing was carried over from the previous DNS host (Kapsi). The domain sends and receives no mail, so it publishes a null MX, `v=spf1 -all` and DMARC `p=reject` to stop spoofing.
  - A CAA record allows only Let's Encrypt, which Caddy uses, to issue certificates.
- **Provisioning and configuration: Ansible.**
  - The `hetzner.hcloud` collection (maintained by Hetzner) creates the server and firewall.
  - Playbooks configure everything inside the server.
  - Running `ansible-playbook` again after any change applies only what differs, so the repo stays the source of truth and the server doesn't drift.
  - Ansible runs from my laptop over SSH, with nothing installed on the server.
- **Runtime:** Docker Compose. No Kubernetes, since a single 2 GB server gets nothing from a cluster scheduler.
- **Reverse proxy:** Caddy, with automatic Let's Encrypt TLS and one certificate per hostname.
  - Caddy is the only container with published ports (80 and 443).
  - Hetzner's Certificates feature isn't used: it only works with Hetzner Load Balancers, which we don't have.
- **Database:** one Postgres 18 container shared by all projects, with a separate database and role per project. It's reachable only on an internal Compose network and is never published.
- **Migrations run as a one-off container**, kept separate from the API process.
  - Each project has a `migrate` service that runs from the API's own image (life-app: `/migrate up`).
  - The API service declares `depends_on: <migrate>: condition: service_completed_successfully`. `docker compose up -d <api>` then runs the migration first, and replaces the API only if it succeeds. A failed migration leaves the old API serving.
  - The old API serves during the migration, so migrations must work with the previous API version. That's already a rule in life-app, and rollbacks need it anyway.
  - The migrate service can later use a role with schema-change (DDL) rights, while the API's role keeps only data access.
- **Backups:** a nightly `pg_dump` of each database, copied off the server. Hetzner's own server backups aren't used: they copy the whole disk while Postgres is running, so the database copy isn't guaranteed to be consistent.
- **Deploys are pull-based.** GitHub Actions holds no credentials for the server; the server pulls new images from ghcr.io itself. See *Deploy flow*.
- **SSH (admin access):** key-only OpenSSH. The Hetzner firewall allows port 22 only from my home IP. Allowing my workplace VPN's outgoing IPs too was considered and left out for now; it would be a second firewall rule, with the IPs kept in Ansible Vault. No VPN or other access product is added: the main remaining risk is an OpenSSH flaw exploitable before login, and automatic security updates cover that. See *Server baseline*.

## Open decisions

- **Backup location:** Hetzner Storage Box, Object Storage, or another provider. Check current prices first.
- **Monitoring:** an external uptime check and alerts for a failed deploy or backup.

## Hetzner resources (Ansible `hetzner.hcloud`)

- **Server:** as above, with my SSH key added at creation and both a public IPv4 and IPv6 address. Hetzner's own backups stay off.
- **Cloud Firewall:**
  - Inbound: allow TCP 80 and 443 from anywhere, plus ICMP.
  - TCP 22 only from a `home` rule (my current home IP).
  - The home IP is stored in the repo, encrypted with Ansible Vault (`home_ip.vault.yaml`), so the repo stays the source of truth and the rule never depends on the network the playbook runs from. My home IP isn't guaranteed to stay the same, so `scripts/set-home-ip.sh` stores my current public IP and applies only the firewall (`--tags firewall`). Each change is a commit.
  - Rule changes affect only new connections, so an open SSH session survives them. Hetzner doesn't document how fast changes apply; in practice it's seconds.
  - This firewall filters traffic before it reaches the server. Docker's published ports bypass `ufw` on the server, so this is the firewall that counts.
- **The Hetzner API token and the Ansible Vault password** live in 1Password, so any computer signed in to it can run the playbooks. `ansible.cfg` gets the vault password through `scripts/vault-password.sh` (`op read`), and the token is exported as `HCLOUD_TOKEN`. Neither is ever in the repo.
- **DNS zone** `lakaniemi.com`, with delete protection. See *DNS* under *Decisions*.
- Nothing else: no load balancer, volumes, floating IPs, private networks or certificates.

## Server baseline (Ansible playbook)

- **Admin user:** `valtteri`, a non-root user with `sudo`, which asks for the user's password. Root login over SSH is off, so a stolen SSH key alone doesn't give root.
  - The password is stored only in Ansible Vault (`vault_admin_password`), not in 1Password, so 1Password keeps holding only the keys: the vault password, the Hetzner token and the SSH key.
  - It's 32 characters of letters and digits, without look-alikes (0/O, 1/l/I). It may have to be typed into the web console, where keyboard layouts and symbols are unreliable. That still leaves about 185 bits.
  - It was generated once, straight into the vault file (`admin_password.vault.yaml`), so it was never printed or pasted anywhere.
  - The base role sets it from the vault, hashed with a fixed salt (`vault_admin_password_salt`, generated with the password) so re-runs report no changes. Ansible's `ansible_become_password` reads the same vault variable, so runs need no extra input.
  - **Bootstrap:** Hetzner puts the SSH key only in root's `authorized_keys`, so the first run connects as root with `-e ansible_user=root`. Every later run uses the default, the admin user. A separate bootstrap playbook, or a fallback that detects whether to connect as root, was more code for a one-time run. The sshd reload is a handler, so it runs at the end of the play and the open root connection isn't needed after it.
  - SSH password login is off, so outside `sudo` the password works only on Hetzner's web console, the recovery path if SSH from home stops working. To read it there, use `ansible-vault view` on any computer with the repo and 1Password.
- **SSH** (`sshd_config.d/10-hardening.conf` drop-in): sshd uses the first value it reads for each setting, so the drop-in sorts before cloud-init's `50-cloud-init.conf`. The role validates it with `sshd -t` before reloading sshd.
  - `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`
  - `AllowUsers <admin>`, `AllowAgentForwarding no`, `X11Forwarding no`
  - `LogLevel VERBOSE`, to log each login's key fingerprint
- **Key:** Ed25519, stored in 1Password (`hetzner-ssh-key`) and served by the 1Password SSH agent. The private key never sits on disk, every login asks for Touch ID, and the key follows me to any computer signed in to 1Password. A FIDO2 `ed25519-sk` key, e.g. a YubiKey, is optional and stronger.
- **Updates:** `unattended-upgrades` installs Ubuntu security updates daily.
  - When an update needs a reboot (typically a new kernel), it reboots at 04:00 UTC (`Automatic-Reboot-Time`).
  - Docker (from Docker's apt repo) and the container images (pinned in `stack/`) aren't updated automatically. I update them deliberately through Ansible.
- **Recovery after a reboot:** Docker starts at boot and brings back every `restart: unless-stopped` container.
  - Docker ignores Compose's `depends_on` here, so the API may start before Postgres accepts connections. The API's startup ping then fails and Docker restarts it until Postgres is up, usually within seconds.
  - Migrate services have no restart policy, so they don't run again at boot. Nothing needs migrating, since the image didn't change.
  - Postgres has `stop_grace_period: 60s`, so it can shut down cleanly instead of being killed after Docker's default 10 seconds.
  - The systemd timers start again at boot. The backup timer has `Persistent=true`, so a backup missed while the server was down runs right after boot.
  - Caddy's certificates are in a volume, so it doesn't request new ones after a reboot.
- **Docker** (Engine and Compose plugin, from Docker's apt repo):
  - default log rotation (`json-file` with `max-size`/`max-file`), so container logs can't fill the 40 GB disk;
  - the admin user isn't in the `docker` group, so Docker runs through `sudo` (`docker` group membership is effectively root);
  - `restart: unless-stopped` on every service.
- **Other:** a 1 GB swap file as a safety margin, and the timezone set to UTC, which also makes the 04:00 reboot time UTC.
  - The base role uses only `ansible.builtin` modules, so the timezone is set through `/etc/localtime` and the SSH key is written with `copy`. `community.general` and `ansible.posix` would be pinned dependencies for a single module each.

## Repo layout

```
infra/
  README.md                  setup, running the playbooks, day-to-day operations
  CLAUDE.md                  rules for AI agents working in this repo
  docs/design.md             this document
  ansible/
    inventory/hcloud.yaml    the server, found through the Hetzner API by label
    group_vars/all/          server settings, DNS records, vault-encrypted secrets
    provision.yaml           Hetzner resources and DNS (hetzner.hcloud)
    site.yaml                everything inside the server
    roles/                   base (users, SSH, updates, swap), docker, stack, deploy, backup
  stack/                     copied to the server by the stack role
    compose.yaml             caddy, postgres, and include: of projects/*.yaml
    projects/life-app.yaml   life-migrate and life-api services
    caddy/Caddyfile          one block per hostname
    postgres/init/           creates per-project databases and roles on first start
  deploy/deploy.sh           pull-based deploy (below)
  deploy/projects.conf       per project: image, Compose service, health URL
  backup/pg-dump.sh          nightly dumps
  systemd/                   deploy and backup timers and services
  scripts/set-home-ip.sh     stores my current IP as the home IP and updates the firewall (run from home)
  scripts/vault-password.sh  reads the Ansible Vault password from 1Password
  .env.example               variables the server's .env must define
```

- **Secrets:** the server's `.env` (root-owned, mode 600) holds Postgres passwords and each API's settings, such as `DATABASE_URL` and Google client IDs. Ansible writes it from Ansible Vault, so the encrypted secrets can live in the repo.
- **Postgres init:** scripts in `postgres/init/` run only on an empty data volume. For a project added later, a playbook task creates its database and role.
- **Networks:** `web` connects Caddy and the APIs. `db` connects Postgres and the APIs. Postgres isn't on `web`.
- **Caddy:** `reverse_proxy` with `lb_try_duration` set. Caddy then holds requests for the second or two an API restarts, instead of returning errors.

## Deploy flow

**In the app repo's CI** (on `main`, after tests pass):
1. Build and push `ghcr.io/lakaniemi/<image>:<sha>`, using the built-in `GITHUB_TOKEN` with `packages: write`.
2. Point the `:production` tag at the new image.
3. Poll the public health endpoint until it reports the new SHA. Fail the run after a timeout.

CI has no access to the server.

**On the server**, `deploy.sh` runs every minute from a systemd timer, under `flock` so runs can't overlap. For each project in `projects.conf`:
1. Resolve `:production` to a digest. Stop if it equals the deployed digest stored in `/var/lib/deploy/<project>`.
2. Pull the image by digest, then `up -d` the API. Compose runs the project's migrate service first and replaces the API only if the migration succeeds.
3. Wait for its health check. On success, record the digest. On failure, log the error and leave the digest unrecorded, so the next run retries.

**Rollback:** move `:production` back to an older SHA's image. Migrations only move forward, and the project's migration rules keep the previous API version working with the new schema.

**Infra changes** (Caddyfile, a new project, an SSH setting) are committed and applied from my laptop with `ansible-playbook ansible/site.yaml`.

**Who can deploy:** whoever can push `:production` to the image's package. Keep that limited to the app repo's own workflows:
- Link each image package to its repo, so access follows the repo's.
- No personal access tokens with `write:packages`.
- Turn on 2FA for my GitHub account, and branch protection on `main`.
- Pull requests from forks and from Dependabot get a read-only `GITHUB_TOKEN`, so they can't push images.

Signed build attestations (verifying where each image was built) were considered and left out. With a single maintainer, they would mainly add protection against a leaked package token, which these rules already avoid.

## Changes needed in life-app (separate PR there)

Done in [life-app#19](https://github.com/lakaniemi/life-app/pull/19):
- An advisory lock in `migrations.NewProvider`.
- The `version` field on `GET /health`.
- The CI `publish` job, which pushes `:<sha>` and `:production`.
- The hosting decision in `CLAUDE.md`.

Still to do:
- **Health poll in CI:** after publishing, poll `https://life-app-api.lakaniemi.com/health` until it reports the new SHA. This comes once the server and DNS exist.
- **App config:** point the production API URL at `https://life-app-api.lakaniemi.com`.
- **Package visibility:** make the `life-api` ghcr.io package public after its first publish.

## Build order

1. Write the `provision.yaml` playbook and create the Hetzner resources.
2. DNS: `provision.yaml` creates the zone and records. Check them against Hetzner's nameservers with `dig`, then switch the domain's nameservers at Namecheap to Hetzner's.
3. Write the base role and run `site.yaml`. Document Ansible Vault usage in the README: viewing, editing and adding encrypted files, e.g. reading the admin password for the web console. Then verify:
   - SSH works from home;
   - port 22 is closed from any other IP (e.g. from a phone hotspot);
   - `set-home-ip.sh` updates the rule;
   - the Hetzner web console login works;
   - running the playbook a second time reports no changes.
4. Add the docker and stack roles with Caddy and Postgres, and check that TLS works on a placeholder hostname.
5. life-app: add the health poll to CI and set the app's production API URL.
6. Add the deploy role. Do the first deploy end to end, then test a rollback by moving `:production` back.
7. Backups: add the backup role once the backup location is decided, and do a test restore.
