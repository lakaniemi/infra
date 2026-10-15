#!/usr/bin/env bash
# Stores this machine's public IP as the home IP in Ansible Vault and points the
# firewall's home SSH rule at it. Run it from home, then commit the vault file.
set -euo pipefail

cd "$(dirname "$0")/.."

HCLOUD_TOKEN="${HCLOUD_TOKEN:-$(op read "op://Private/hetzner-cloud-api/api-token")}"
export HCLOUD_TOKEN

file=ansible/group_vars/all/home_ip.vault.yaml

ip="$(curl -fsS https://api.ipify.org)"
if [[ ! "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Unexpected response from api.ipify.org: $ip" >&2
  exit 1
fi

# Re-encrypting changes the file even when the IP is the same, so skip it then.
if [[ -f "$file" ]]; then
  current="$(ansible-vault view "$file" | awk '/^home_ip:/ { print $2 }')"
  if [[ "$current" == "$ip" ]]; then
    echo "Home IP is already $ip"
    exit 0
  fi
  echo "Home IP: $current -> $ip"
else
  echo "Home IP: $ip"
fi

printf 'home_ip: %s\n' "$ip" | ansible-vault encrypt --output "$file" -
ansible-playbook ansible/provision.yaml --tags firewall

echo "Commit $file to record the change."
