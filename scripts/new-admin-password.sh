#!/usr/bin/env bash
# Generates the admin user's password and hash salt straight into Ansible Vault, so
# the password is never shown. Read it with ansible-vault view.
set -euo pipefail

cd "$(dirname "$0")/.."

file=ansible/group_vars/all/admin_password.vault.yaml

if [[ -f "$file" ]]; then
  echo "$file already exists." >&2
  exit 1
fi

# Prints $2 random characters from the tr character set $1. Reading a fixed amount
# instead of all of /dev/urandom avoids SIGPIPE failing the pipeline.
random_chars() {
  local chars
  chars="$(head -c 4096 /dev/urandom | LC_ALL=C tr -dc "$1")"
  if (( ${#chars} < $2 )); then
    echo "Not enough random characters" >&2
    exit 1
  fi
  printf '%s' "${chars:0:$2}"
}

# Letters and digits without look-alikes (0/O, 1/l/I), since the password may have
# to be typed in Hetzner's web console.
password="$(random_chars 'A-HJ-NP-Za-km-z2-9' 32)"
salt="$(random_chars 'A-Za-z0-9' 16)"

printf 'vault_admin_password: %s\nvault_admin_password_salt: %s\n' "$password" "$salt" |
  ansible-vault encrypt --output "$file" -

echo "Created $file. Commit it, then run ansible/site.yaml."
