# infra

Ansible configuration for the shared Hetzner server that runs my hobby projects' APIs and their Postgres databases, and for the `lakaniemi.com` DNS zone. See [docs/design.md](docs/design.md) for the decisions behind it.

## Setup

1. Install the tools:
   ```sh
   brew install ansible ansible-lint shellcheck 1password-cli
   ansible-galaxy collection install -r ansible/requirements.yaml -p .ansible/collections
   ```
   Homebrew's Ansible already includes `hetzner.hcloud`, which bundles the `hcloud` Python library it needs. The last command installs it into the project too, because `ansible-lint` doesn't see Homebrew's copy.
2. Turn on the 1Password app's CLI integration (Settings → Developer → Integrate with 1Password CLI), so `op` unlocks with Touch ID.
3. Secrets live in 1Password, in the `Private` vault:
   - `infra-ansible-vault`, field `password`: the Ansible Vault password. `ansible.cfg` reads it through `scripts/vault-password.sh`, so every command that needs it finds it on its own.
   - `hetzner-cloud-api`, field `api-token`: a Hetzner Cloud API token with read and write access.
   - `hetzner-ssh-key`: an SSH Key item (Ed25519) for logging in to the server. `provision.yaml` uploads its public key to Hetzner.
4. Turn on the 1Password SSH agent (Settings → Developer → Use the SSH agent) and let 1Password update `~/.ssh/config` when it offers to, or follow its [setup guide](https://developer.1password.com/docs/ssh/get-started/). The private key never leaves 1Password, and each SSH login, including Ansible's, asks for Touch ID.
5. In each shell where you run Ansible, export the token:
   ```sh
   export HCLOUD_TOKEN="$(op read op://Private/hetzner-cloud-api/api-token)"
   ```
   `scripts/set-home-ip.sh` reads the token from 1Password on its own if it isn't exported.

## Provisioning

`provision.yaml` creates the SSH key, firewall, server and DNS zone. Store the home IP first (see below), then run:

```sh
ansible-playbook ansible/provision.yaml
```

Running it again applies only what changed, and a run with no changes should report none. Use `--tags server`, `--tags firewall` or `--tags dns` to run one part.

## Setting the home IP

The firewall allows SSH only from the home IP, which is stored encrypted in `ansible/group_vars/all/home_ip.vault.yaml`. To set it, or to update it after it changes, run this from home:

```sh
scripts/set-home-ip.sh
```

It stores the current public IP, updates only the firewall, and asks you to commit the vault file. Running the playbook from another network doesn't change the rule. Open SSH sessions survive the change.

## DNS

`lakaniemi.com` is served by Hetzner's nameservers; Namecheap only points at them. Records are defined in `ansible/group_vars/all/dns.yaml`. To add a service hostname, add it to `dns_service_hostnames` and run:

```sh
ansible-playbook ansible/provision.yaml --tags dns
```

## Validation

```sh
ansible-lint
ansible-playbook --syntax-check ansible/provision.yaml
shellcheck scripts/*.sh
```
