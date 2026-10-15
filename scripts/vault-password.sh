#!/usr/bin/env bash
# Prints the Ansible Vault password from 1Password. ansible.cfg runs this instead of
# reading a password file, so the password never sits on disk in plaintext.
set -euo pipefail

op read "op://Private/infra-ansible-vault/password"
