# CLAUDE.md

Ansible configuration for the shared Hetzner server that hosts my hobby projects' APIs and Postgres, plus the `lakaniemi.com` DNS zone.

- Read `docs/design.md` before changing anything. It holds the decisions and their reasons. When a decision changes, update it in the same PR.
- This repo is public. Never commit tokens or passwords in plaintext: secrets go in Ansible Vault, whose password and the Hetzner token (`HCLOUD_TOKEN`) live in 1Password. DNS records and the server's public IPs are public anyway.
- Playbooks must stay idempotent: running one a second time reports no changes.
- DNS records are defined in `ansible/group_vars/all/dns.yaml`. Never change them in the Hetzner console.
- Every service gets its own `<project>-api.lakaniemi.com` hostname, never a generic one like `api.`. Apps never use IPs.
- Database migrations must keep working with the previous API version, since the old API serves while they run and rollbacks rely on it.
- Validate changes with `ansible-lint`, `ansible-playbook --syntax-check` and `shellcheck`. Both Ansible commands read the vault password from 1Password through `scripts/vault-password.sh`, so they may prompt for Touch ID.
- Collections are pinned in `ansible/requirements.yaml` and installed into `.ansible/collections`, which `ansible.cfg` puts ahead of the older copies bundled with Homebrew's Ansible. Reinstall after changing the pin. `hetzner.hcloud` bundles the `hcloud` Python library, so nothing else is needed.
- Keep the README to direct instructions. Reasons and background go in `docs/design.md`.
