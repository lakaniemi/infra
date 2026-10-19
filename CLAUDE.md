# CLAUDE.md

Ansible configuration for the shared Hetzner server that hosts my hobby projects' APIs and Postgres, plus the `lakaniemi.com` DNS zone.

- Read the README and `docs/` before changing anything. Update them in the same PR when a change affects them.
- This repo is public. Never commit tokens or passwords in plaintext: secrets go in Ansible Vault, whose password and the Hetzner token (`HCLOUD_TOKEN`) live in 1Password. DNS records and the server's public IPs are public anyway.
- Playbooks must stay idempotent: running one a second time reports no changes.
- DNS records are defined in `ansible/group_vars/all/dns.yaml`. Never change them in the Hetzner console. Deleting an entry there doesn't delete the record at Hetzner: run it once with `state: absent` first, then remove it.
- Every service gets its own `<project>-api.lakaniemi.com` hostname, never a generic one like `api.`. Apps never use IPs. The infra's own endpoints are the exception: new webhooks go under `webhooks.lakaniemi.com/<hook>`.
- The webhook listener must stay powerless: it only creates trigger files, never runs commands or gets the Docker socket. Privileged work happens in host systemd units that decide for themselves what to do.
- Validate changes with `ansible-lint`, `ansible-playbook --syntax-check` and `shellcheck`. Both Ansible commands read the vault password from 1Password through `scripts/vault-password.sh`, so they may prompt for Touch ID.
- The collections pinned in `ansible/requirements.yaml` need no other Python packages, locally or on the server.
- Keep the README to direct instructions. The reason for a non-obvious choice goes in a comment next to the code it explains.
