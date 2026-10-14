#!/usr/bin/env bash
# Points the Hetzner firewall's "home" SSH rule at this machine's current public IP.
# Requires hcloud, jq, curl and HCLOUD_TOKEN.
set -euo pipefail

firewall="${1:-hobby}"

: "${HCLOUD_TOKEN:?HCLOUD_TOKEN must be set}"

ip="$(curl -fsS https://api.ipify.org)"
rules="$(hcloud firewall describe "$firewall" -o json | jq '.rules')"

old="$(jq -r '.[] | select(.description == "home") | .source_ips | join(", ")' <<<"$rules")"
if [[ -z "$old" ]]; then
  echo "No rule with description \"home\" in firewall $firewall" >&2
  exit 1
fi
if [[ "$old" == "$ip/32" ]]; then
  echo "Home rule already allows $ip"
  exit 0
fi

jq --arg cidr "$ip/32" 'map(if .description == "home" then .source_ips = [$cidr] else . end)' <<<"$rules" |
  hcloud firewall replace-rules --rules-file - "$firewall" >/dev/null

echo "Home rule: $old -> $ip/32"
