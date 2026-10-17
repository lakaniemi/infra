#!/usr/bin/env bash
# Deploys each project in projects.conf whose image's :production tag has
# moved since its last deploy. deploy.timer runs it every minute.
set -euo pipefail

readonly config=/etc/deploy/projects.conf
readonly state_dir=/var/lib/deploy
readonly compose=(docker compose -f /opt/stack/compose.yaml)
readonly health_timeout=60

# systemd never starts the service twice at once, but a manual run could
# overlap with the timer's.
exec 9>/run/lock/deploy.lock
if ! flock -n 9; then
  echo "Another deploy is running" >&2
  exit 0
fi

# Errors are handled explicitly: set -e doesn't apply inside a function called
# as `deploy ... || status=1`.
deploy() {
  local project=$1 image=$2 service=$3 health_url=$4
  local var state_file digest target current image_id container body version deadline
  var="$(tr 'a-z-' 'A-Z_' <<<"$project")_IMAGE"
  state_file="$state_dir/$project.env"

  if ! digest=$(docker buildx imagetools inspect "$image:production" \
    --format '{{json .Manifest.Digest}}' | jq -r .); then
    echo "$project: can't resolve $image:production" >&2
    return 1
  fi
  target="$image@$digest"

  if ! current=$(sed -n "s/^$var=//p" "$state_file"); then
    echo "$project: can't read $state_file" >&2
    return 1
  fi
  if [[ $current == "$target" ]]; then
    return 0
  fi

  echo "$project: deploying $target, replacing $current"
  if ! docker pull --quiet "$target" >/dev/null; then
    echo "$project: pulling $target failed" >&2
    return 1
  fi

  # The variable takes precedence over the state file, which changes only once
  # the deploy succeeds. Compose replaces the API only if the migration passes.
  if ! env "$var=$target" "${compose[@]}" up --detach "$service"; then
    echo "$project: compose up failed" >&2
    return 1
  fi

  # Also catches a site.yaml run that put the old image back meanwhile.
  image_id=$(docker image inspect --format '{{.Id}}' "$target")
  container=$("${compose[@]}" ps --quiet "$service")
  if [[ -z $container ]] ||
    [[ $(docker inspect --format '{{.Image}}' "$container") != "$image_id" ]]; then
    echo "$project: $service isn't running $target" >&2
    return 1
  fi

  deadline=$((SECONDS + health_timeout))
  until body=$(curl --fail --silent --max-time 5 "$health_url") &&
    [[ $(jq -r .status <<<"$body" 2>/dev/null) == ok ]]; do
    if ((SECONDS >= deadline)); then
      echo "$project: $health_url not ok after ${health_timeout}s: ${body:-no response}" >&2
      return 1
    fi
    sleep 2
  done
  version=$(jq -r .version <<<"$body")

  # Without the version as a tag: the image reference must stay the one the
  # containers were created with, or the next site.yaml run recreates them.
  if ! printf '# Version %s\n%s=%s\n' "$version" "$var" "$target" >"$state_file.tmp" ||
    ! mv "$state_file.tmp" "$state_file"; then
    echo "$project: deployed $version, but couldn't record it in $state_file" >&2
    return 1
  fi
  echo "$project: deployed $version"
}

status=0
# Read on fd 3, so commands in the loop can't consume the list from stdin.
while read -r project image service health_url <&3; do
  [[ -z $project || $project == \#* ]] && continue
  deploy "$project" "$image" "$service" "$health_url" || status=1
done 3<"$config"
exit "$status"
