"""Tells Argo CD which preview stacks should exist (ADR 0010).

An Argo CD ApplicationSet plugin generator: Argo CD POSTs to
/api/v1/getparams.execute and gets back one parameter set per stack.

A stack exists for every branch with an open pull request labelled `preview`
in any of the three app repos. For each part (API, SMS site, cadet portal) it
runs that branch's preview image when the repo has one, otherwise main's, so
one label previews a change that spans repos as well as one that doesn't. The
images are referenced by digest, so a push that moves the tag rolls the stack.

Standard library only: it runs from a ConfigMap on the stock python image,
with no image of its own to build.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("preview-resolver")

# part -> (GitHub repo, ghcr.io image). The part names are the Helm values the
# stack chart reads (<part>Image).
PARTS = {
    "api": ("BenMcD23/SMS_Scrapers_API", "benmcd23/sms_scrapers_api"),
    "site": ("BenMcD23/317_SMS_Site", "benmcd23/317_sms_site"),
    "portal": ("BenMcD23/317_Cadet_Portal", "benmcd23/317_cadet_portal"),
}
LABEL = os.environ.get("PREVIEW_LABEL", "preview")
# home has room for a few, not for every open pull request.
MAX_STACKS = int(os.environ.get("MAX_STACKS", "3"))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
# Unauthenticated, GitHub allows 60 requests an hour and one answer costs
# three, so it's cached long enough to stay under that. With a token, the
# label shows up about as fast as Argo CD asks.
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "30" if GITHUB_TOKEN else "240"))
PLUGIN_TOKEN = os.environ.get("PLUGIN_TOKEN", "")

MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


def slug(branch: str) -> str:
    """The branch as a DNS label: namespace, tailnet names and image tag.

    Must match the Tag step of each app repo's preview-image.yml, which pushes
    preview-<slug>. 40 characters leaves room for the pv- and -portal around it
    in a 63-character tailnet name."""
    return re.sub(r"[^a-z0-9]+", "-", branch.lower()).strip("-")[:40].rstrip("-")


def _open(req: urllib.request.Request, timeout: float = 15):
    return urllib.request.urlopen(req, timeout=timeout)


def labelled_prs(repo: str) -> list[dict]:
    """Open pull requests in repo carrying the preview label, from branches in
    the repo itself: a fork's branch has no preview image to run."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=100",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "preview-resolver"},
    )
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    with _open(req) as res:
        pulls = json.load(res)
    return [
        {
            "repo": repo,
            "number": p["number"],
            "branch": p["head"]["ref"],
            "created_at": p["created_at"],
        }
        for p in pulls
        if any(label["name"] == LABEL for label in p["labels"])
        and (p["head"].get("repo") or {}).get("full_name") == repo
    ]


def digest(image: str, tag: str) -> str | None:
    """The digest ghcr.io has for image:tag, or None if there is no such tag.

    Only a 404 means "no image". Any other failure raises, so the caller can
    tell a branch that was never built from a registry it couldn't reach."""
    with _open(urllib.request.Request(f"https://ghcr.io/token?scope=repository:{image}:pull")) as res:
        token = json.load(res)["token"]
    req = urllib.request.Request(
        f"https://ghcr.io/v2/{image}/manifests/{tag}",
        method="HEAD",
        headers={"Authorization": f"Bearer {token}", "Accept": MANIFEST_TYPES},
    )
    try:
        with _open(req) as res:
            return res.headers["Docker-Content-Digest"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def stacks() -> list[dict]:
    """One parameter set per stack. Raises if GitHub or ghcr.io can't be read:
    an empty answer would make Argo CD delete every running stack, while an
    error leaves them as they are until the next try."""
    by_branch: dict[str, list[dict]] = {}
    for repo, _ in PARTS.values():
        for pr in labelled_prs(repo):
            by_branch.setdefault(pr["branch"], []).append(pr)

    # Oldest first, so a running stack is never displaced by a newer label:
    # the newer one waits until a slot frees up.
    ordered = sorted(by_branch.items(), key=lambda item: min(pr["created_at"] for pr in item[1]))
    if len(ordered) > MAX_STACKS:
        waiting = ", ".join(branch for branch, _ in ordered[MAX_STACKS:])
        log.warning("%d stacks labelled, running the oldest %d; waiting: %s", len(ordered), MAX_STACKS, waiting)

    out = []
    for branch, prs in ordered[:MAX_STACKS]:
        params = {
            "slug": slug(branch),
            "branch": branch,
            "pullRequests": ", ".join(f"{pr['repo'].split('/')[1]}#{pr['number']}" for pr in prs),
        }
        for part, (_, image) in PARTS.items():
            found = digest(image, f"preview-{slug(branch)}") or digest(image, "preview-main")
            if not found:
                # Not even main has been built yet (a repo's first preview
                # build hasn't run). Skip the stack rather than deploy a pod
                # that can never start.
                log.warning("%s: no preview image for %s, not even preview-main; skipping", branch, image)
                break
            params[f"{part}Image"] = f"ghcr.io/{image}@{found}"
        else:
            out.append(params)
    return out


class Cache:
    """The last answer, reused for CACHE_SECONDS. Argo CD asks on its own
    schedule and on every ApplicationSet event, which would otherwise spend
    GitHub's rate limit."""

    def __init__(self, compute, ttl: float, clock=time.monotonic):
        self._compute, self._ttl, self._clock = compute, ttl, clock
        self._lock = threading.Lock()
        self._value, self._at = None, None

    def get(self):
        with self._lock:
            if self._at is None or self._clock() - self._at >= self._ttl:
                # A failure propagates and keeps nothing, so the next request
                # tries again rather than serving the error for the whole TTL.
                self._value, self._at = self._compute(), self._clock()
            return self._value


CACHE = Cache(stacks, CACHE_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/v1/getparams.execute":
            return self._reply(404, {"error": "not found"})
        if PLUGIN_TOKEN and self.headers.get("Authorization") != f"Bearer {PLUGIN_TOKEN}":
            return self._reply(403, {"error": "bad token"})
        try:
            params = CACHE.get()
        except Exception:
            log.exception("couldn't work out the stacks")
            return self._reply(500, {"error": "couldn't read GitHub or ghcr.io; see the resolver's log"})
        self._reply(200, {"output": {"parameters": params}})

    def do_GET(self):
        # Liveness only: deliberately doesn't touch GitHub.
        self._reply(200 if self.path == "/healthz" else 404, {})

    def _reply(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        log.info(fmt, *args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
