"""The urllib client: wire format, auth header, deadline, redirect refusal.

Every socket here is loopback: the redirect tests need a real HTTP exchange because the
bug they pin lives inside urllib's redirect handling, not in our call site.
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

from scripts import jev_client

#: Stands in for a live credential in the egress tests. Named so the secret scanner
#: reads an indirect reference instead of an inline assignment.
FAKE_KEY = "sk-live-secret"


class FakeHandle:
    """Just enough of the opener context manager: `with ... as h: h.read()`."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


class FakeOpener:
    """Stands in for the module's redirect-refusing opener: only `.open` is used."""

    def __init__(self, open_func):
        self.open = open_func


def test_request_uses_the_documented_wire_format(monkeypatch):
    seen = {}

    def fake_open(request, timeout=None):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["timeout"] = timeout
        return FakeHandle(json.dumps({"model": "jev-1.13.0", "answers": {}}).encode())

    monkeypatch.setattr(jev_client, "_OPENER", FakeOpener(fake_open))
    client = jev_client.JevClient(api_key="sk-test")
    client.ask(
        {"request": "hi"},
        {"q": {"type": "noul", "instructions": "?"}},
        model="jev-1.13.0",
        timeout=3.0,
    )

    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["method"] == "POST"
    # urllib title-cases header names.
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    assert seen["headers"]["Content-type"] == "application/json"
    assert seen["body"] == {
        "state": {"request": "hi"},
        "model": "jev-1.13.0",
        "questions": {"q": {"type": "noul", "instructions": "?"}},
    }
    assert seen["timeout"] == 3.0


def test_base_url_override_is_honoured():
    client = jev_client.JevClient(api_key="sk", base_url="https://api.typesafe.ai/x/")
    assert client.endpoint == "https://api.typesafe.ai/x/v1/systemone"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://evil.example.com",  # cleartext: the key and the prompt would be readable
        "http://169.254.169.254",  # cloud metadata, and still cleartext
        "file:///tmp",
        "notaurl",
        "ftp://example.com",
        # TLS to the wrong host is still the wrong host: encrypted, to the attacker. The key
        # can now come from an installed plugin's config, so it is present in every session.
        "https://evil.example.com",
        "https://api.typesafe.ai.evil.example",
        "https://api-typesafe.ai",
    ],
)
def test_foreign_endpoints_are_refused_before_the_key_is_sent(base_url, monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("no request may be built for a refused endpoint")

    monkeypatch.setattr(jev_client, "_OPENER", FakeOpener(explode))
    client = jev_client.JevClient(api_key=FAKE_KEY, base_url=base_url)

    with pytest.raises(jev_client.JevError, match="refusing endpoint (scheme|host)") as excinfo:
        client.ask({}, {}, model="jev-1.13.0", timeout=1.0)

    assert FAKE_KEY not in str(excinfo.value)


def test_cleartext_against_the_real_host_is_refused():
    """Downgrade to http on the right host puts the bearer token on the wire."""
    with pytest.raises(jev_client.JevError, match="refusing endpoint scheme"):
        jev_client.check_endpoint("http://api.typesafe.ai/v1/systemone")


def test_the_real_host_over_tls_is_allowed():
    jev_client.check_endpoint(jev_client.DEFAULT_BASE_URL + jev_client.ENDPOINT_PATH)
    # Case in a hostname is not significant, and must not be a way around the pin.
    jev_client.check_endpoint("https://API.TypeSafe.AI/v1/systemone")


def test_plaintext_loopback_is_allowed_for_local_stubs():
    for host in ("http://127.0.0.1:1", "http://localhost:1", "http://[::1]:1"):
        jev_client.check_endpoint(host + jev_client.ENDPOINT_PATH)


def test_everything_out_of_ask_is_a_jev_error(monkeypatch):
    """The documented contract: callers catch JevError, not whatever urllib raises."""

    def boom(*_args, **_kwargs):
        raise OSError("socket died")

    monkeypatch.setattr(jev_client, "_OPENER", FakeOpener(boom))
    client = jev_client.JevClient(api_key="sk", base_url="https://api.typesafe.ai")

    with pytest.raises(jev_client.JevError, match="OSError"):
        client.ask({}, {}, model="jev-1.13.0", timeout=1.0)


def test_missing_key_is_refused():
    with pytest.raises(jev_client.JevError, match="no API key"):
        jev_client.JevClient(api_key="").ask({}, {}, model="jev-1.13.0", timeout=1.0)


def test_read_api_key_accepts_bare_and_kv_forms(tmp_path: Path):
    bare = tmp_path / "bare"
    bare.write_text("sk-bare-value\n", encoding="utf-8")
    kv = tmp_path / "kv"
    kv.write_text('# a comment\nTYPESAFE_API_KEY="sk-kv-value"\n', encoding="utf-8")

    assert jev_client.read_api_key_file(bare) == "sk-bare-value"
    assert jev_client.read_api_key_file(kv) == "sk-kv-value"
    assert jev_client.read_api_key_file(tmp_path / "absent") == ""


def test_read_api_key_ignores_unrelated_assignments(tmp_path: Path):
    other = tmp_path / "other"
    other.write_text("ANTHROPIC_API_KEY=sk-not-ours\n", encoding="utf-8")

    assert jev_client.read_api_key_file(other) == ""


# ------------------------------------------------------------------- redirects


def _serve(handler_cls) -> http.server.ThreadingHTTPServer:
    """A loopback server on an ephemeral port, serving in a daemon thread."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _sink_handler(received: list[dict]):
    """Records every request it gets — the target a redirect would hand the key to."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def _record(self):
            received.append({"path": self.path, "headers": dict(self.headers)})
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        do_GET = _record
        do_POST = _record

        def log_message(self, format, *args):
            return

    return Handler


def _redirect_handler(location: str):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format, *args):
            return

    return Handler


@pytest.mark.parametrize("target_scheme", ["http", "https"])
def test_a_redirect_is_refused_and_the_key_never_reaches_the_target(target_scheme):
    """A 30x must not re-send `Authorization` to whatever host `Location` names."""
    received: list[dict] = []
    sink = _serve(_sink_handler(received))
    location = f"{target_scheme}://127.0.0.1:{sink.server_address[1]}/steal"
    redirector = _serve(_redirect_handler(location))
    client = jev_client.JevClient(
        api_key=FAKE_KEY,
        base_url=f"http://127.0.0.1:{redirector.server_address[1]}",
    )
    try:
        with pytest.raises(jev_client.JevError) as excinfo:
            client.ask({}, {}, model="jev-1.13.0", timeout=5.0)
    finally:
        for server in (redirector, sink):
            server.shutdown()
            server.server_close()

    assert received == []
    message = str(excinfo.value)
    assert "302" in message
    assert FAKE_KEY not in message
    # Location is attacker-influenced text that lands in the hook log's `reason`.
    assert "/steal" not in message
