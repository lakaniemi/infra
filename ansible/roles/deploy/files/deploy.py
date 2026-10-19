#!/usr/bin/python3
"""Deploys each project whose image's :production tag has moved.

deploy.path starts it when the deploy webhook leaves a trigger file, and
deploy.timer once after boot. For each project in projects.json, it resolves
:production to a digest. If that differs from the deployed image, it pulls it
and runs `compose up` for the API, which migrates first. It records the image
only once the API runs it and reports healthy.
"""

import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG = Path("/etc/deploy/projects.json")
STATE_DIR = Path("/var/lib/deploy")
TRIGGER_DIR = Path("/var/lib/webhooks/deploy")
COMPOSE_FILE = "/opt/stack/compose.yaml"
LOCK_FILE = "/run/lock/deploy.lock"
HEALTH_TIMEOUT = 60
# Both end up in the deployed-image file, which decides what runs, so only
# these shapes may get in.
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
VERSION = re.compile(r"[0-9A-Za-z._-]{1,64}")
# Multi-platform images have an index; single-platform ones only a manifest.
MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


class DeployError(Exception):
    pass


def log(project, message, file=sys.stdout):
    print(f"{project}: {message}", file=file, flush=True)


def docker(*args, env=None, capture=False):
    result = subprocess.run(["docker", *args], env=env, capture_output=capture, text=True)
    if result.returncode != 0:
        detail = f": {result.stderr.strip()}" if capture else ""
        raise DeployError(f"`docker {' '.join(args)}` failed{detail}")
    return result.stdout.strip() if capture else None


def registry_token(challenge):
    """Gets an anonymous pull token, as described by a 401's WWW-Authenticate."""
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    query = urllib.parse.urlencode({k: fields[k] for k in ("service", "scope") if k in fields})
    with urllib.request.urlopen(f"{fields['realm']}?{query}", timeout=30) as response:
        body = json.load(response)
    return body.get("token") or body["access_token"]


def production_digest(image):
    """Asks the registry which digest :production points at, without pulling."""
    registry, _, repository = image.partition("/")
    request = urllib.request.Request(
        f"https://{registry}/v2/{repository}/manifests/production",
        method="HEAD",
        headers={"Accept": MANIFEST_TYPES},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.headers["Docker-Content-Digest"]
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise
        token = registry_token(error.headers["WWW-Authenticate"])
    request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.headers["Docker-Content-Digest"]


def deployed_image(state_file, var):
    try:
        lines = state_file.read_text().splitlines()
    except OSError as error:
        raise DeployError(f"can't read the deployed image: {error}") from error
    for line in lines:
        name, _, value = line.partition("=")
        if name == var:
            return value
    raise DeployError(f"{state_file} doesn't set {var}")


def wait_until_healthy(url):
    """Returns the version the health endpoint reports once its status is ok."""
    deadline = time.monotonic() + HEALTH_TIMEOUT
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = json.load(response)
            if body.get("status") == "ok":
                version = body.get("version")
                if isinstance(version, str) and VERSION.fullmatch(version):
                    return version
                return "unknown"
            last = json.dumps(body)
        except (OSError, ValueError) as error:
            last = str(error)
        if time.monotonic() >= deadline:
            raise DeployError(f"{url} not ok after {HEALTH_TIMEOUT}s: {last}")
        time.sleep(2)


def deploy(name, image, service, health_url):
    var = f"{name.upper().replace('-', '_')}_IMAGE"
    state_file = STATE_DIR / f"{name}.env"

    try:
        digest = production_digest(image)
    except (OSError, ValueError, KeyError) as error:
        raise DeployError(f"can't resolve {image}:production: {error}") from error
    if not DIGEST.fullmatch(digest or ""):
        raise DeployError(f"no valid digest for {image}:production: {digest}")
    target = f"{image}@{digest}"
    current = deployed_image(state_file, var)
    if current == target:
        log(name, f"up to date, running {target}")
        return

    log(name, f"deploying {target}, replacing {current}")
    docker("pull", "--quiet", target, capture=True)
    # The variable takes precedence over the state file, which changes only once
    # the deploy succeeds. Compose replaces the API only if the migration passes.
    docker(
        "compose", "-f", COMPOSE_FILE, "up", "--detach", service,
        env={**os.environ, var: target},
    )

    # Also catches a site.yaml run that put the old image back meanwhile.
    container = docker("compose", "-f", COMPOSE_FILE, "ps", "--quiet", service, capture=True)
    running = None
    if container:
        running = docker("inspect", "--format", "{{.Image}}", container, capture=True)
    if running != docker("image", "inspect", "--format", "{{.Id}}", target, capture=True):
        raise DeployError(f"{service} isn't running {target}")
    version = wait_until_healthy(health_url)

    # Without the version as a tag: the image reference must stay the one the
    # containers were created with, or the next site.yaml run recreates them.
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(f"# Version {version}\n{var}={target}\n")
    temporary.replace(state_file)
    log(name, f"deployed version {version}")

    # A rollback pulls it again. When current is the reference a new server
    # starts with (…:production), only that tag goes: the image stays under
    # its digest reference.
    result = subprocess.run(["docker", "image", "rm", current], capture_output=True, text=True)
    if result.returncode != 0:
        log(name, f"couldn't remove the previous image: {result.stderr.strip()}", sys.stderr)


def main():
    with open(LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Removed before deploying, so a trigger arriving during this run starts
        # another one: deploy.path checks the directory again when this exits.
        for trigger in TRIGGER_DIR.glob("*"):
            trigger.unlink(missing_ok=True)

        failed = False
        for project in json.loads(CONFIG.read_text()):
            try:
                deploy(**project)
            except DeployError as error:
                log(project["name"], error, sys.stderr)
                failed = True
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
