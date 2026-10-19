# infra

Ansible configuration for the shared Hetzner server that runs my hobby projects' APIs and their Postgres databases, and for the `lakaniemi.com` DNS zone.

On the server, Docker Compose runs Caddy in front of each project's API, one Postgres shared by all projects, and a webhook listener. The listener only creates trigger files; systemd units on the host react to them, e.g. by deploying. Unfinished work is listed in [docs/todo.md](docs/todo.md).

## Setup

1. Install the tools:
   ```sh
   brew install ansible ansible-lint shellcheck 1password-cli
   ansible-galaxy collection install --force -r ansible/requirements.yaml
   ```
2. Turn on the 1Password app's CLI integration (Settings → Developer → Integrate with 1Password CLI).
3. Create these items in 1Password, in the `Private` vault:
   - `infra-ansible-vault`, field `password`: the Ansible Vault password.
   - `hetzner-cloud-api`, field `api-token`: a Hetzner Cloud API token with read and write access.
   - `hetzner-ssh-key`: an SSH Key item (Ed25519) for logging in to the server.
4. Turn on the 1Password SSH agent (Settings → Developer → Use the SSH agent) and let 1Password update `~/.ssh/config`, or follow its [setup guide](https://developer.1password.com/docs/ssh/get-started/).
5. In each shell where you run Ansible, export the token:
   ```sh
   export HCLOUD_TOKEN="$(op read op://Private/hetzner-cloud-api/api-token)"
   ```

## Provisioning

Set the home IP first (see below), then run:

```sh
ansible-playbook ansible/provision.yaml
```

Use `--tags server`, `--tags firewall` or `--tags dns` to run one part.

## Configuring the server

The first run on a new server connects as root. Accept the server's host key first, using the IP from `ansible-inventory --host hobby`:

```sh
ssh root@<ip> true
ansible-playbook ansible/site.yaml -e ansible_user=root
```

After that, root login is off. Run it without the override:

```sh
ansible-playbook ansible/site.yaml
```

Do a dry run first. It shows what would change without changing anything:

```sh
ansible-playbook ansible/site.yaml --check --diff
```

A dry run of a change that adds a service or systemd unit fails at the tasks that start it, since the dry run didn't install it. The real run works.

Use `--tags base`, `--tags docker`, `--tags stack` or `--tags deploy` to run one role.

## Rebuilding the server

This reinstalls the server from `server_image` in `ansible/group_vars/all/vars.yaml`, e.g. for a new Ubuntu release. It wipes the disk, databases included; the IPs stay the same.

1. Dump each database that holds real data on the server, then copy the dumps to your computer with `scp`:
   ```sh
   sudo docker compose -f /opt/stack/compose.yaml exec -T postgres pg_dump -U postgres life_app > ~/life_app.sql
   ```
2. Rebuild it, and type the server name when asked:
   ```sh
   ansible-playbook ansible/provision.yaml --tags rebuild
   ```
3. Replace the old host key, using the IP from `ansible-inventory --host hobby`:
   ```sh
   ssh-keygen -R <ip>
   ssh root@<ip> true
   ```
4. Configure it as a new server, connecting as root:
   ```sh
   ansible-playbook ansible/site.yaml -e ansible_user=root --check --diff
   ansible-playbook ansible/site.yaml -e ansible_user=root
   ```

## The Compose stack

`stack/` is copied to `/opt/stack` on the server. Docker needs `sudo` there:

```sh
sudo docker compose -f /opt/stack/compose.yaml ps
sudo docker compose -f /opt/stack/compose.yaml logs -f life-app-api
```

Files deleted from `stack/` stay in `/opt/stack` until you remove them there by hand.

### Postgres

- Changing a database password in the vault doesn't change it in Postgres. Run `ALTER ROLE <role> PASSWORD '<password>'` in `psql` as well:
  ```sh
  sudo docker compose -f /opt/stack/compose.yaml exec postgres psql -U postgres
  ```
- The scripts in `stack/postgres/init/` run only when the data volume is empty. If one fails on a new server, fix it, remove the volume and run `site.yaml` again:
  ```sh
  sudo docker compose -f /opt/stack/compose.yaml down
  sudo docker volume rm hobby_pgdata
  ```

### Adding a project's settings

The stack role stops if a setting is missing. To add or change one, e.g. life-app's Google client IDs:

```sh
ansible-vault edit ansible/group_vars/all/life_app.vault.yaml
```

Add or edit the line:

```yaml
vault_life_app_google_client_ids: <id>.apps.googleusercontent.com
```

Use the **Web** OAuth client ID from Google Cloud. Separate several IDs with commas. Then run `site.yaml`.

### Updating Caddy, Postgres or the webhook listener's Python

Their images are pinned in `stack/compose.yaml` as `<image>:<tag>@<digest>`. To update one:

1. Look up the new tag's digest:
   ```sh
   docker buildx imagetools inspect caddy:<tag> --format '{{json .Manifest.Digest}}'
   ```
2. Replace both the tag and the digest in `stack/compose.yaml`.
3. Commit, then run `site.yaml`.

Project images are deployed instead (see below).

## Deploys

A project's CI deploys by moving its image's `:production` tag and then calling the deploy webhook:

```sh
curl -fsS -X POST -H "Authorization: Bearer $DEPLOY_WEBHOOK_TOKEN" https://webhooks.lakaniemi.com/deploy
```

The server then deploys every project in `deploy_projects` (`ansible/group_vars/all/vars.yaml`) whose `:production` has moved. It also checks once after each boot.

### Giving a project repo the token

```sh
ansible-vault view ansible/group_vars/all/webhooks.vault.yaml \
  | sed -n 's/^vault_webhook_deploy_token: //p' \
  | gh secret set DEPLOY_WEBHOOK_TOKEN -R lakaniemi/<repo>
```

### On the server

- Deploy now, without the webhook:
  ```sh
  sudo touch /var/lib/webhooks/deploy/requested
  ```
- Deploy logs:
  ```sh
  sudo journalctl -u deploy -f
  ```
- The deployed image and version of each project:
  ```sh
  cat /var/lib/deploy/*.env
  ```

To roll back, point `:production` back at an older version from the project's repo.

### Adding a webhook

Each hook is `POST https://webhooks.lakaniemi.com/<hook>` with its own token. To add one:

1. Add it to `webhook_hooks` in `ansible/group_vars/all/vars.yaml`.
2. Add its token as `vault_webhook_<hook>_token` (`openssl rand -hex 32`) to `webhooks.vault.yaml`, expose it in `vars.yaml`, and pass it to the listener as `WEBHOOK_<HOOK>_TOKEN` through `ansible/roles/stack/templates/env.j2` and `stack/compose.yaml`. Add it to the secrets check in `ansible/roles/stack/tasks/main.yaml` too.
3. Add a `.path` unit watching `/var/lib/webhooks/<hook>` and the service it starts, like `deploy.path` and `deploy.service` in `ansible/roles/deploy/files/`.

## Ansible Vault

Ansible reads the vault password from 1Password, so these commands need no password file.

- View an encrypted file, e.g. the admin password for Hetzner's web console:
  ```sh
  ansible-vault view ansible/group_vars/all/admin_password.vault.yaml
  ```
- Edit one in `$EDITOR`:
  ```sh
  ansible-vault edit ansible/group_vars/all/<name>.vault.yaml
  ```
- Add one, then reference each variable in `ansible/group_vars/all/vars.yaml` under a plain name (`foo: "{{ vault_foo }}"`):
  ```sh
  ansible-vault create ansible/group_vars/all/<name>.vault.yaml
  ```
  Prefix the variables in it with `vault_`.

## Setting the home IP

SSH is allowed only from the home IP. To set it, or to update it after it changes, run this from home and commit the vault file it changes:

```sh
scripts/set-home-ip.sh
```

## DNS

The domain is registered at Namecheap, whose only job is pointing its nameservers at Hetzner's. Records are defined in `ansible/group_vars/all/dns.yaml`. To add a service hostname, add it to `dns_service_hostnames` and run:

```sh
ansible-playbook ansible/provision.yaml --tags dns
```

## Validation

```sh
ansible-lint
ansible-playbook --syntax-check ansible/provision.yaml
ansible-playbook --syntax-check ansible/site.yaml
shellcheck scripts/*.sh stack/postgres/init/*.sh
```
