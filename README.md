# infra

Ansible configuration for the shared Hetzner server that runs my hobby projects' APIs and their Postgres databases, and for the `lakaniemi.com` DNS zone. See [docs/design.md](docs/design.md) for the decisions behind it.

## Setup

1. Install the tools:
   ```sh
   brew install ansible ansible-lint hcloud jq shellcheck
   "$(brew --prefix ansible)/libexec/bin/pip" install hcloud
   ansible-galaxy collection install -r ansible/requirements.yaml -p .ansible/collections
   ```
   Homebrew's Ansible already includes `hetzner.hcloud`. The last command installs it into the project too, because `ansible-lint` doesn't see Homebrew's copy.
2. Create a Hetzner Cloud API token with read and write access, and export it. Keep it in a password manager, never in the repo:
   ```sh
   export HCLOUD_TOKEN=...
   ```
3. Optional, until the work VPN's outgoing IPs are confirmed: put them in an encrypted vault file. Keep the vault password in the password manager too.
   ```sh
   ansible-vault create ansible/group_vars/all/vault.yaml
   ```
   ```yaml
   vault_work_vpn_ips:
     - 203.0.113.0/24
   ```
   Without this file, the firewall has no `work-vpn` rule. Once it exists, add `--ask-vault-pass` to every `ansible-playbook` command.

## Provisioning

`provision.yaml` creates the SSH key, firewall, server and DNS zone, using `~/.ssh/id_ed25519.pub` by default (override with `-e ssh_public_key_path=...`):

```sh
ansible-playbook ansible/provision.yaml
```

Running it again applies only what changed, and a run with no changes should report none. Use `--tags server` or `--tags dns` to run one part.

The firewall's `home` SSH rule is set to the public IP of the machine running the playbook. When running it from somewhere else, such as the work VPN, pass `-e home_ip=<home IP>`.

## Updating the home IP

When the home IP changes, run this from home:

```sh
scripts/allow-home-ip.sh
```

It changes only the `home` rule, and open SSH sessions survive the change.

## DNS cutover (one-off)

1. Run `provision.yaml` and note the nameservers it prints.
2. Check the records on Hetzner's nameservers:
   ```sh
   dig +short @hydrogen.ns.hetzner.com life-app-api.lakaniemi.com A
   dig +short @hydrogen.ns.hetzner.com life-app-api.lakaniemi.com AAAA
   ```
3. In Namecheap: Domain List → `lakaniemi.com` → Nameservers → Custom DNS, and enter the nameservers from step 1.
4. Run `ansible-playbook ansible/provision.yaml --tags dns` again until `delegation_status` is `valid`, and check that `dig +short NS lakaniemi.com` shows Hetzner's nameservers.

## Validation

```sh
ansible-lint
ansible-playbook --syntax-check ansible/provision.yaml
shellcheck scripts/*.sh
```
