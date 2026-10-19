# infra

Configuration for the shared Hetzner server that runs my hobby projects' APIs and their Postgres databases. The first project is life-app (`lakaniemi/life-app`).

## Decisions

- **Server:** Hetzner Cloud **CPX12** (1 vCPU, 2 GB RAM, 40 GB NVMe) in **HEL1** (Helsinki). €11.99/month before VAT (€15.05 with Finnish VAT), plus €0.50/month before VAT for the IPv4 address. Upgrade the server type when projects need more.
  - **Ubuntu 26.04 LTS.** A new LTS is adopted once its first point release (e.g. 26.04.1) is out, as Ubuntu itself does before offering upgrades to it. The server started on 24.04 and was rebuilt on 26.04 while it held only test data.
- **IPv4 and IPv6 are both enabled.**
  - IPv4-only client networks couldn't reach the server without IPv4.
  - `github.com` and `ghcr.io` have no IPv6 addresses, so the server couldn't pull images without IPv4.
- **DNS:** every service has its own hostname on `lakaniemi.com`, named after the project, e.g. `life-app-api.lakaniemi.com`. No project gets a generic name like `api.`. The infra's own endpoints are the exception: webhooks are served from `webhooks.lakaniemi.com` (see *Webhooks*). Each hostname has A and AAAA records. Apps never use an IP, so moving servers is a DNS change, never an app update.
  - The zone is hosted on Hetzner DNS and managed by Ansible (`hetzner.hcloud` `zone` and `zone_rrset`), so records live in the repo and the service records follow the server's IPs automatically.
  - The domain is registered at Namecheap, whose only role is pointing the nameservers at Hetzner.
  - The zone started fresh: nothing was carried over from the previous DNS host (Kapsi). The domain sends and receives no mail, so it publishes a null MX, `v=spf1 -all` and DMARC `p=reject` to stop spoofing.
  - A CAA record allows only Let's Encrypt, which Caddy uses, to issue certificates.
- **Provisioning and configuration: Ansible.**
  - The `hetzner.hcloud` collection (maintained by Hetzner) creates the server and firewall.
  - Playbooks configure everything inside the server.
  - Running `ansible-playbook` again after any change applies only what differs, so the repo stays the source of truth and the server doesn't drift.
  - Ansible runs from my laptop over SSH, with nothing installed on the server.
  - `group_vars` sit next to the playbooks in `ansible/`, so only playbooks would load them. `ansible.cfg` sets `playbook_dir = ansible`, so ad-hoc commands (`ansible hobby -m …`) load them too.
  - Collections are pinned in `ansible/requirements.yaml` (`hetzner.hcloud`, `community.docker`) and installed into `.ansible/collections`. The install uses `--force`, because Homebrew's Ansible bundles its own copies, and `ansible-galaxy` would otherwise skip one that already satisfies the pin.
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
- **Deploys are triggered, then pulled.** GitHub Actions can only ask the server to check for a new image, through a webhook. The server then looks up `:production` on ghcr.io and pulls it itself, so CI holds no credentials that can choose or change what runs. See *Webhooks* and *Deploy flow*.
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
- **Changing the server's OS:** `server_image` applies only when the server is created. `hetzner.hcloud.server` with `state: present` ignores image changes, so a new Ubuntu release is installed by a **rebuild** (`provision.yaml --tags rebuild`).
  - A rebuild keeps the server, its IPs and its firewall, so DNS and the home rule don't change. Hetzner puts the creation SSH key back for root, so `site.yaml` bootstraps it like a new server. It wipes the disk, including Postgres and Caddy's certificates, and gives the server a new SSH host key.
  - The rebuild tasks carry Ansible's special `never` tag, so they run only when `--tags rebuild` is given, never in a normal run. They ask for the server name first, lift the protection only for the rebuild, and turn it back on afterwards. Hetzner requires delete and rebuild protection to have the same value, so delete protection is off for those few minutes too.
  - Once there's real data, take and copy off a `pg_dump` first (see *Backups*).
  - Creating a second server and moving DNS to it would avoid the downtime, but means new IPs and more steps. It's worth it once there are real users.
- Nothing else: no load balancer, volumes, floating IPs, private networks or certificates.

## Server baseline (Ansible playbook)

- **Admin user:** `valtteri`, a non-root user with `sudo`, which asks for the user's password. Root login over SSH is off, so a stolen SSH key alone doesn't give root.
  - The password is stored only in Ansible Vault (`vault_admin_password`), not in 1Password, so 1Password keeps holding only the keys: the vault password, the Hetzner token and the SSH key.
  - It's 32 characters of letters and digits, without look-alikes (0/O, 1/l/I). It may have to be typed into the web console, where keyboard layouts and symbols are unreliable. That still leaves about 185 bits.
  - It was generated once, straight into the vault file (`admin_password.vault.yaml`), so it was never printed or pasted anywhere.
  - The base role sets it from the vault, hashed with a fixed salt (`vault_admin_password_salt`, generated with the password) so re-runs report no changes. Ansible's `ansible_become_password` reads the same vault variable, so runs need no extra input.
  - Ubuntu 26.04's `sudo` is `sudo-rs`, which shows Ansible's password prompt in a different form, so Ansible times out waiting for it. Ansible runs the original sudo instead (`ansible_become_exe: /usr/bin/sudo.ws`, installed alongside), and the server keeps Ubuntu's default for interactive use. Making the original sudo the system default with `update-alternatives` was the alternative; it changes more for the same result.
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
    roles/deploy/files/      deploy.py (see Deploy flow) and its systemd units
  stack/                     copied to the server by the stack role
    compose.yaml             caddy, postgres, webhooks, and include: of projects/*.yaml
    projects/life-app.yaml   life-app-migrate and life-app-api services
    caddy/Caddyfile          one block per hostname
    postgres/init/           creates per-project databases and roles on first start
    webhooks/listener.py     turns webhook requests into trigger files (see Webhooks)
  scripts/set-home-ip.sh     stores my current IP as the home IP and updates the firewall (run from home)
  scripts/vault-password.sh  reads the Ansible Vault password from 1Password
  .env.example               variables the server's .env must define
```

- **Secrets:** the server's `.env` (root-owned, mode 600) holds Postgres passwords, the webhook tokens and each API's settings, such as `DATABASE_URL` and Google client IDs. Ansible writes it from Ansible Vault, so the encrypted secrets can live in the repo.
  - Variables are prefixed per project (`LIFE_APP_…`), and each service picks its own through `${…:?}` interpolation. Postgres never sees an API's settings, and a missing variable stops `up` with an error naming it.
  - Included project files use the main `compose.yaml`'s `.env` too, so one file serves the whole stack.
  - The passwords were generated straight into the vault files (`openssl rand -hex 32` piped into `ansible-vault encrypt`), so they were never printed. Hex needs no escaping in `DATABASE_URL`.
  - Google client IDs aren't secret, since they ship inside the app, but they're in Ansible Vault with the project's other settings.
- **Postgres init:** scripts in `postgres/init/` run only on an empty data volume. For a project added later, a playbook task creates its database and role.
  - Each project's role owns its database, so its migrations can create tables in `public`.
  - The scripts are executable, so they run as their own process with `set -euo pipefail`. A non-executable one would be sourced into the image's entrypoint instead, and Docker Desktop fails to run it at all, so a local test wouldn't match the server.
  - If an init script fails, Postgres restarts and skips initialisation, because the data directory now exists. On a new server, remove the `hobby_pgdata` volume and run the playbook again.
  - Changing a password in the vault later doesn't change it in Postgres: init doesn't run again. Rotating one needs an `ALTER ROLE` as well.
  - The healthcheck uses `pg_isready -h 127.0.0.1`. While the init scripts run, Postgres listens only on its Unix socket, so a socket check would report it ready too early.
- **Networks:** `web` connects Caddy, the APIs and the webhook listener. `db` connects Postgres and the APIs. Postgres isn't on `web`.
  - `db` is `internal: true`, so Postgres has no route to the internet. The APIs reach the internet (e.g. Google's signing keys) through `web`.
- **Caddy:** `reverse_proxy` with `lb_try_duration` set. Caddy then holds requests for the second or two an API restarts, instead of returning errors.
  - The `caddy/` directory is mounted, not the Caddyfile alone. Ansible replaces files by renaming a new one over them, and a single-file bind mount would keep showing the old file.
  - HTTP/3 is off (`protocols h1 h2`): it runs over UDP, which the Hetzner firewall doesn't allow.
- **Images are pinned as `tag@digest`** (e.g. `caddy:2.11.7@sha256:…`). Docker pulls by the digest, so a moved tag can't change what runs; the tag shows which version it is.
  - Project images aren't pinned in the repo: deploy.py records them on the server (see *Deploy flow*), so `site.yaml` never rolls back what it deployed.
- **The stack role** copies `stack/` to `/opt/stack` and runs `docker compose up` through `community.docker.docker_compose_v2`. The module supports `--check` (through compose's `--dry-run`) and reports which containers changed; a `command` task would do neither.
  - A dry run (`--check`) copies nothing, so later tasks see the server as it is: Compose reads the current stack files, and systemd knows only the installed units. Changes to `stack/` show in the copy task's diff. A change that adds a new service or unit fails its dry run at the tasks that need it, e.g. restarting the service or enabling the unit; that's expected, and the real run works. Only steady-state changes are kept dry-run clean: making first-time setup simulate would mean check-mode conditions on tasks that rarely need them.
  - `copy` sends every file in `stack/`, tracked or not, and doesn't delete files removed from it; remove those on the server by hand.
  - `up` starts each project's exited migrate container again, every run. That's harmless (no pending migrations, under the migration lock), so the role doesn't count it as a change. Creating or recreating a migrate container, e.g. for a new image, still counts.
  - A change in `stack/` triggers a graceful `caddy reload`.
  - For a new server or project, it creates the project's deployed-image file pointing at `:production`, before `up`. It never changes an existing one.
  - `stack/webhooks/` is copied first, on its own, so a change to the listener restarts it: Compose doesn't notice changed files in a bind mount.

## Webhooks

`POST https://webhooks.lakaniemi.com/<hook>` with `Authorization: Bearer <token>` asks the server to do something. `deploy` is the only hook so far.

- **The webhook only signals; the server decides.** The listener creates an empty trigger file in `/var/lib/webhooks/<hook>/`, answers 202 and does nothing else. A systemd `.path` unit on the host watches that directory and starts the hook's service, which works out what to do on its own (for `deploy`: from ghcr.io). This is how Flux's `Receiver` and Argo CD's webhooks work: a request only says "check now", and its body decides nothing.
  - A stolen token can only make the server check early. It can't choose what runs.
  - The more common single-server setup, e.g. `adnanh/webhook` or Watchtower's HTTP API, runs the deploy inside the receiver. The internet-facing process then needs the Docker socket, which is root-equivalent.
- **A file links the listener and the service.** File permissions are the privilege boundary, and nothing on the host listens on the network.
  - Having the listener start the service over D-Bus, allowed by a polkit rule, was considered. It would put the system D-Bus socket in an internet-facing container, with polkit as the only barrier, and polkit rules on unit names are known to be fragile.
  - Triggers collapse: the service removes the file when it starts, and systemd checks the directory again when the service exits. A trigger during a run starts one more run, and a burst starts only one.
  - `sudo touch /var/lib/webhooks/<hook>/requested` triggers a hook by hand.
- **The listener** is ~50 lines of standard-library Python (`stack/webhooks/listener.py`) in the official `python:*-slim` image.
  - It runs as `nobody`, with a read-only filesystem, no capabilities and no Docker socket. Its only writable mount is `/var/lib/webhooks`, and only the per-hook directories belong to `nobody`.
  - A hook exists when its token (`WEBHOOK_<HOOK>_TOKEN`) is set and its directory exists. Each hook has its own token in Ansible Vault, so a leaked token triggers only its hook.
  - It compares tokens in constant time and never reads the request body; Caddy also limits bodies to 1 KB. A bearer token is enough, since there's no body to sign: GitHub's HMAC signatures protect payloads.
  - Adding a hook: add it to `webhook_hooks`, add its token, and add a `.path` unit and service for it.
- The token is also a GitHub Actions secret in each repo that deploys. CI calls the hook itself, instead of a repository webhook configured in GitHub, so the run that published the image also sees whether the deploy happened (see *Deploy flow*).

## Deploy flow

**In the app repo's CI** (on `main`, after tests pass):
1. Build and push `ghcr.io/lakaniemi/<image>:<sha>`, using the built-in `GITHUB_TOKEN` with `packages: write`.
2. Point the `:production` tag at the new image.
3. Call the deploy hook.
4. Poll the public health endpoint until it reports the new SHA. Fail the run after a timeout.

The hook is called once. If a deploy fails or the call is lost, the run fails, and re-running it retries. GitHub doesn't redeliver failed webhooks either, so CI checking the result is what makes this reliable.

**On the server**, `deploy.service` runs `/usr/local/bin/deploy` (`ansible/roles/deploy/files/deploy.py`, standard-library Python) when `deploy.path` sees a trigger file, and once after boot from `deploy.timer`. The boot run catches a `:production` move made while the server was down. It removes the trigger files, then, for each project in `/etc/deploy/projects.json` (written from `deploy_projects` in `group_vars`):
1. Resolve `:production` to a digest through the registry API, without pulling. Stop if it equals the deployed image.
2. Pull the image by digest, then `up -d` the API with `<PROJECT>_IMAGE` set to it in the environment. Compose runs the project's migrate service first, and replaces the API only if the migration succeeds.
3. Check that the API's container runs the new image, then wait for `/health` to report `status: ok`.
4. On success, record the image in the deployed-image file. The previous image stays until the weekly prune (see *Server baseline*). On failure, log the error to the journal (`journalctl -u deploy`) and leave the file unchanged.

Details:
- **The deployed-image file**, `/var/lib/deploy/<project>.env`, holds `<PROJECT>_IMAGE=<image>@<digest>`, plus the version as a comment. The project's `include:` in `compose.yaml` reads it through `env_file`, which adds to the variables from `.env`.
  - Every `docker compose` command, including the stack role's, uses the deployed image, so `site.yaml` doesn't roll back a deploy.
  - A variable in the shell takes precedence over the env file. That's how deploy.py tries an image before recording it.
  - The image reference has no version tag. Compose would see a new reference as a changed service, and the next `site.yaml` run would recreate the containers.
- **The health check confirms the image, not the version.** The image has no label with its commit, so deploy.py can't tell which version to expect. Comparing versions is CI's job (step 4). The image check also catches a `site.yaml` run that put the old image back during a deploy.
- `TimeoutStartSec=15min` stops a hung pull, migration or health check from blocking later deploys.

**Rollback:** move `:production` back to an older SHA's image, through a manually started workflow in the app repo that points `:production` at the existing `:<sha>` image without rebuilding, then calls the deploy hook. Migrations only move forward, and the project's migration rules keep the previous API version working with the new schema.

**Infra changes** (Caddyfile, a new project, an SSH setting) are committed and applied from my laptop with `ansible-playbook ansible/site.yaml`.

**Who can deploy:** whoever can push `:production` to the image's package. The deploy hook's token isn't a deploy right: it only makes the server check `:production` sooner. Keep pushing limited to the app repo's own workflows:
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

Also done: the `life-app-api` ghcr.io package is public, so the server pulls it without credentials.

Still to do:
- **Deploy hook and health poll in CI:** after publishing, call `https://webhooks.lakaniemi.com/deploy` with the token from an Actions secret, then poll `https://life-app-api.lakaniemi.com/health` until it reports the new SHA.
- **Rollback workflow:** a `workflow_dispatch` job that takes a SHA, points `:production` at `:<sha>` (`docker buildx imagetools create`) and calls the deploy hook, in the same concurrency group as `publish`.
- **App config:** point the production API URL at `https://life-app-api.lakaniemi.com`.

## Build order

1. **Done.** Write the `provision.yaml` playbook and create the Hetzner resources.
2. **Done.** DNS: `provision.yaml` creates the zone and records. Check them against Hetzner's nameservers with `dig`, then switch the domain's nameservers at Namecheap to Hetzner's.
3. **Done.** Write the base role and run `site.yaml`. Document Ansible Vault usage in the README: viewing, editing and adding encrypted files, e.g. reading the admin password for the web console. Then verify:
   - SSH works from home;
   - port 22 is closed from any other IP (e.g. from a phone hotspot);
   - `set-home-ip.sh` updates the rule;
   - the Hetzner web console login works;
   - running the playbook a second time reports no changes.
4. **Done.** Add the docker and stack roles with Caddy, Postgres and the life-app API. Then verify:
   - `https://life-app-api.lakaniemi.com/health` answers with a Let's Encrypt certificate and reports the deployed version;
   - only ports 80 and 443 answer from outside, not Postgres;
   - the containers come back after a reboot;
   - running the playbook a second time reports no changes.
5. Add the webhook listener and the deploy role. Then verify:
   - the deploy hook answers 202 with the token, and 401 without it;
   - a trigger deploys `:production`, and a second one finds it up to date;
   - running the playbook a second time reports no changes.
6. life-app: add the deploy hook and health poll to CI, the rollback workflow, and the app's production API URL. Then deploy a new version end to end, and test a rollback.
7. Backups: add the backup role once the backup location is decided, and do a test restore.
