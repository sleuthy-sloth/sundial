"""How the built app is served.

The files under /assets carry a hash of their contents in their name, and the shell,
manifest and service worker do not. Getting that distinction wrong is how a phone keeps
opening the previous app after an upgrade, so the policy is pinned here rather than left
to the browser's guess.

These run against a throwaway site directory, so they need no build.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spa import SpaStaticFiles, cache_control_for


def site(root: Path) -> Path:
    """A directory shaped like the built app."""
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><script src=/assets/index-abc123.js></script>")
    (root / "assets" / "index-abc123.js").write_text("console.log('app')")
    (root / "sw.js").write_text("// service worker")
    (root / "manifest.webmanifest").write_text('{"name": "sundial"}')
    (root / "icon-192.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return root


def served(root: Path):
    probe = FastAPI()
    probe.mount("/", SpaStaticFiles(directory=root, html=True), name="spa")
    return TestClient(probe)


def test_a_hashed_asset_may_be_kept_forever(tmp_path):
    """Its name changes when its contents do, so age can never make it wrong."""
    with served(site(tmp_path / "site")) as client:
        response = client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_the_shell_must_be_asked_about(tmp_path):
    """`/` keeps its name across every deploy, so it can never be trusted on age alone."""
    with served(site(tmp_path / "site")) as client:
        for path in ("/", "/index.html"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-cache", path


def test_the_service_worker_and_manifest_must_be_asked_about(tmp_path):
    """A stale worker script is the one that keeps serving the old bundle."""
    with served(site(tmp_path / "site")) as client:
        for path in ("/sw.js", "/manifest.webmanifest", "/icon-192.png"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers["cache-control"] == "no-cache", path


def test_no_asset_is_served_without_a_policy(tmp_path):
    """Anything added to the build gets a policy whether or not it was thought about."""
    with served(site(tmp_path / "site")) as client:
        for path in ("/", "/sw.js", "/assets/index-abc123.js"):
            assert "cache-control" in client.get(path).headers, path


def test_the_policy_is_decided_by_the_directory(tmp_path):
    """Stated once, so a new file cannot quietly get the wrong answer."""
    assert cache_control_for("assets/index-abc123.js") == "public, max-age=31536000, immutable"
    assert cache_control_for("index.html") == "no-cache"
    assert cache_control_for("sw.js") == "no-cache"
    assert cache_control_for("icon-192.png") == "no-cache"
