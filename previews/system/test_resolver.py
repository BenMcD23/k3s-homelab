"""Tests for resolver.py. Standard library only, like the resolver:

    python3 -m unittest discover -s previews/system      (or: make test)

GitHub and ghcr.io are faked at resolver._open; nothing touches the network.
"""

import io
import json
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import resolver


def pr(number, branch, created="2026-10-01T00:00:00Z", labels=("preview",), repo=None):
    return {
        "number": number,
        "created_at": created,
        "labels": [{"name": n} for n in labels],
        "head": {"ref": branch, "repo": {"full_name": repo} if repo else None},
    }


class Fake:
    """GitHub and ghcr.io as dicts: pulls[repo] is the open PR list, tags[image]
    the tags that exist. errors maps a URL substring to an HTTP status."""

    def __init__(self, pulls=None, tags=None, errors=None):
        self.pulls = pulls or {}
        self.tags = tags or {}
        self.errors = errors or {}
        self.calls = []

    def __call__(self, req, timeout=15):
        url = req.full_url
        self.calls.append(url)
        for fragment, code in self.errors.items():
            if fragment in url:
                raise urllib.error.HTTPError(url, code, "fake", {}, io.BytesIO(b""))
        if url.startswith("https://api.github.com/repos/"):
            repo = url.removeprefix("https://api.github.com/repos/").split("/pulls")[0]
            # A PR from the repo itself unless the test said otherwise.
            pulls = [
                {**p, "head": {**p["head"], "repo": p["head"]["repo"] or {"full_name": repo}}}
                for p in self.pulls.get(repo, [])
            ]
            return _response(json.dumps(pulls))
        if url.startswith("https://ghcr.io/token"):
            return _response(json.dumps({"token": "t"}))
        if url.startswith("https://ghcr.io/v2/"):
            image, tag = url.removeprefix("https://ghcr.io/v2/").split("/manifests/")
            if tag in self.tags.get(image, ()):
                return _response("", {"Docker-Content-Digest": f"sha256:{image.split('/')[1]}-{tag}"})
            raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))
        raise AssertionError(f"unexpected request {url}")


def _response(body, headers=None):
    res = mock.MagicMock()
    res.__enter__.return_value = res
    res.read.return_value = body.encode()
    res.headers = headers or {}
    # json.load reads via .read()
    return res


API, SITE, PORTAL = (repo for repo, _ in resolver.PARTS.values())
ALL_MAIN = {image: {"preview-main"} for _, image in resolver.PARTS.values()}


class SlugTest(unittest.TestCase):
    # Copied from the Tag step of the app repos' preview-image.yml. The two
    # must agree, or the resolver looks for a tag CI never pushed.
    WORKFLOW = (
        "printf '%s' \"$1\" | tr '[:upper:]' '[:lower:]' "
        "| sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-40 | sed -E 's/-+$//'"
    )

    def test_matches_the_ci_workflow(self):
        for branch in [
            "main",
            "ccr-a4977126-d42341",
            "Feature/Stores_Orders",
            "--odd--name--",
            "dependabot/npm_and_yarn/next-16.4.2",
            "a-very-long-branch-name-that-goes-on-and-on-past-forty-characters",
            "abcdefghijklmnopqrstuvwxyz-0123456789abc-def",
        ]:
            ci = subprocess.run(["bash", "-c", self.WORKFLOW, "_", branch], capture_output=True, text=True)
            # $(...) in the workflow drops the trailing newline.
            self.assertEqual(resolver.slug(branch), ci.stdout.rstrip("\n"), branch)

    def test_fits_a_tailnet_name_with_its_prefix_and_suffix(self):
        s = resolver.slug("x" * 100)
        self.assertLessEqual(len(f"pv-{s}-portal"), 63)


class StacksTest(unittest.TestCase):
    def run_with(self, fake, MAX_STACKS=3):
        with mock.patch.object(resolver, "_open", fake), mock.patch.object(resolver, "MAX_STACKS", MAX_STACKS):
            return resolver.stacks()

    def test_nothing_labelled_means_no_stacks(self):
        fake = Fake(pulls={API: [pr(1, "x", labels=("bug",))]}, tags=ALL_MAIN)
        self.assertEqual(self.run_with(fake), [])

    def test_a_branch_only_in_the_api_runs_main_for_the_sites(self):
        tags = {**ALL_MAIN, "benmcd23/sms_scrapers_api": {"preview-main", "preview-fix-stores"}}
        [stack] = self.run_with(Fake(pulls={API: [pr(12, "fix/stores")]}, tags=tags))
        self.assertEqual(stack["slug"], "fix-stores")
        self.assertEqual(stack["branch"], "fix/stores")
        self.assertEqual(stack["apiImage"], "ghcr.io/benmcd23/sms_scrapers_api@sha256:sms_scrapers_api-preview-fix-stores")
        self.assertEqual(stack["siteImage"], "ghcr.io/benmcd23/317_sms_site@sha256:317_sms_site-preview-main")
        self.assertEqual(stack["portalImage"], "ghcr.io/benmcd23/317_cadet_portal@sha256:317_cadet_portal-preview-main")

    def test_a_branch_in_every_repo_is_one_stack_of_all_three(self):
        tags = {image: {"preview-main", "preview-ccr-1"} for image in ALL_MAIN}
        # Labelled in two repos, unlabelled in the third: the third still runs
        # its own branch, because the image exists.
        fake = Fake(
            pulls={API: [pr(3, "ccr-1")], SITE: [pr(9, "ccr-1")], PORTAL: [pr(4, "ccr-1", labels=())]},
            tags=tags,
        )
        [stack] = self.run_with(fake)
        self.assertEqual(stack["pullRequests"], "SMS_Scrapers_API#3, 317_SMS_Site#9")
        for part in resolver.PARTS:
            self.assertTrue(stack[f"{part}Image"].endswith("-preview-ccr-1"), part)

    def test_beyond_the_cap_the_newest_label_waits(self):
        fake = Fake(
            pulls={
                API: [pr(1, "old", created="2026-10-01T00:00:00Z"), pr(2, "newest", created="2026-10-20T00:00:00Z")],
                SITE: [pr(5, "middle", created="2026-10-10T00:00:00Z")],
            },
            tags=ALL_MAIN,
        )
        stacks = self.run_with(fake, MAX_STACKS=2)
        self.assertEqual([s["branch"] for s in stacks], ["old", "middle"])

    def test_a_forks_pull_request_is_ignored(self):
        # Its branch isn't in our repo, so CI never built it.
        fake = Fake(pulls={SITE: [pr(7, "main", repo="someone/317_SMS_Site")]}, tags=ALL_MAIN)
        self.assertEqual(self.run_with(fake), [])

    def test_a_stack_with_no_image_at_all_is_skipped_not_half_deployed(self):
        tags = {**ALL_MAIN, "benmcd23/317_cadet_portal": set()}
        fake = Fake(pulls={API: [pr(1, "a")], SITE: [pr(2, "b")]}, tags=tags)
        self.assertEqual(self.run_with(fake), [])

    def test_github_failing_is_an_error_not_an_empty_list(self):
        # An empty list would make Argo CD delete every running stack.
        fake = Fake(pulls={API: [pr(1, "a")]}, tags=ALL_MAIN, errors={"317_SMS_Site/pulls": 403})
        with self.assertRaises(urllib.error.HTTPError):
            self.run_with(fake)

    def test_the_registry_failing_is_an_error_not_a_fallback_to_main(self):
        fake = Fake(pulls={API: [pr(1, "a")]}, tags=ALL_MAIN, errors={"/manifests/preview-a": 500})
        with self.assertRaises(urllib.error.HTTPError):
            self.run_with(fake)

    def test_sends_the_github_token_when_there_is_one(self):
        seen = []

        def spy(req, timeout=15):
            seen.append(req.get_header("Authorization"))
            return Fake()(req, timeout)

        with mock.patch.object(resolver, "_open", spy), mock.patch.object(resolver, "GITHUB_TOKEN", "ghp_x"):
            resolver.labelled_prs(API)
        self.assertEqual(seen, ["Bearer ghp_x"])


class CacheTest(unittest.TestCase):
    def test_reuses_an_answer_until_it_expires(self):
        now, calls = [0.0], []
        cache = resolver.Cache(lambda: calls.append(1) or len(calls), ttl=60, clock=lambda: now[0])
        self.assertEqual(cache.get(), 1)
        now[0] = 59
        self.assertEqual(cache.get(), 1)
        now[0] = 60
        self.assertEqual(cache.get(), 2)

    def test_a_failure_is_retried_next_time_not_cached(self):
        results = iter([RuntimeError("down"), "ok"])

        def compute():
            r = next(results)
            if isinstance(r, Exception):
                raise r
            return r

        cache = resolver.Cache(compute, ttl=600, clock=lambda: 0.0)
        with self.assertRaises(RuntimeError):
            cache.get()
        self.assertEqual(cache.get(), "ok")


class HandlerTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), resolver.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, token="", path="/api/v1/getparams.execute"):
        req = urllib.request.Request(self.url + path, data=b'{"input":{"parameters":{}}}', method="POST")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            # Straight to the test server, never through a proxy.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=5) as res:
                return res.status, json.load(res)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_answers_in_the_plugin_generator_format(self):
        cache = mock.Mock(get=mock.Mock(return_value=[{"slug": "a"}]))
        with mock.patch.object(resolver, "CACHE", cache), mock.patch.object(resolver, "PLUGIN_TOKEN", "s"):
            self.assertEqual(self.post("s"), (200, {"output": {"parameters": [{"slug": "a"}]}}))

    def test_a_failed_lookup_is_a_500_so_argo_keeps_the_running_stacks(self):
        cache = mock.Mock(get=mock.Mock(side_effect=OSError("network down")))
        with mock.patch.object(resolver, "CACHE", cache), mock.patch.object(resolver, "PLUGIN_TOKEN", ""):
            code, _ = self.post()
        self.assertEqual(code, 500)

    def test_a_wrong_token_is_refused(self):
        with mock.patch.object(resolver, "PLUGIN_TOKEN", "s"):
            self.assertEqual(self.post("wrong")[0], 403)
            self.assertEqual(self.post("")[0], 403)

    def test_other_paths_are_404(self):
        with mock.patch.object(resolver, "PLUGIN_TOKEN", ""):
            self.assertEqual(self.post(path="/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
