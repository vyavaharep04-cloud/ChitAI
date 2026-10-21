"""Static-asset checks for the browser UI (no browser needed)."""

from __future__ import annotations

import re
from pathlib import Path

from starlette.testclient import TestClient

from chitai.api.server import create_app
from chitai.engine import CHIT_NAMES

WEB = Path(__file__).parents[2] / "web"


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_every_asset_referenced_by_the_page_is_served():
    refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', read("index.html"))
    assert {"/static/style.css", "/static/app.js"} <= set(refs)
    with TestClient(create_app()) as client:
        for ref in refs:
            assert client.get(ref).status_code == 200, ref


def test_the_page_loads_nothing_from_other_hosts():
    for name in ("index.html", "style.css", "app.js"):
        text = read(name)
        assert not re.search(r"(?:src|href)=\"https?://", text), name
        assert "@import" not in text and "url(http" not in text, name


def test_every_engine_chit_name_has_a_presentation_entry():
    script = read("app.js")
    block = script[script.index("const CHIT_STYLE"): script.index("const SEAT_SYMBOLS")]
    styled = set(re.findall(r"^\s+(\w+):\s*\{\s*color:", block, flags=re.MULTILINE))
    assert set(CHIT_NAMES) <= styled


def test_the_client_never_sends_a_seat_or_a_timeout():
    script = read("app.js")
    sent = re.findall(r"send\(\{[^)]*\}\)", script)
    assert sent, "expected send() calls"
    for call in sent:
        assert "seat" not in call and "timeout" not in call.replace("timeout_seconds", ""), call


def test_motion_respects_the_reduced_motion_preference():
    css = read("style.css")
    assert "prefers-reduced-motion: no-preference" in css
    outside = css.split("@media (prefers-reduced-motion: no-preference)")[0]
    assert "animation:" not in outside and "transition:" not in outside
