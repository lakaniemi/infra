# infra

Ansible configuration for the shared Hetzner server that runs my hobby projects' APIs and their Postgres databases, and for the `lakaniemi.com` DNS zone. See [docs/design.md](docs/design.md) for the decisions behind it.

## Setup

1. Install the tools:
   ```sh
   brew install ansible ansible-lint shellcheck 1password-cli
   ansible-galaxy collection install -r ansible/requirements.yaml
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

## Setting the home IP

SSH is allowed only from the home IP. To set it, or to update it after it changes, run this from home and commit the vault file it changes:

```sh
scripts/set-home-ip.sh
```

## DNS

Records are defined in `ansible/group_vars/all/dns.yaml`. To add a service hostname, add it to `dns_service_hostnames` and run:

```sh
ansible-playbook ansible/provision.yaml --tags dns
```

## Validation

```sh
ansible-lint
ansible-playbook --syntax-check ansible/provision.yaml
shellcheck scripts/*.sh
```
