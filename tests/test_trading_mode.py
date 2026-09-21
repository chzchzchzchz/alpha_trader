"""Truth-table tests for the live-trading gate and its wiring into KalshiClient.

No network: place_order is intercepted before any HTTP call is made.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.trading_mode import (  # noqa: E402
    ARM_PHRASE, LIVE, PAPER, LiveTradingNotArmed, resolve_mode,
)
from kalshi.client import KalshiClient, _DEMO, _PROD  # noqa: E402

ENV_KEYS = ("TRADING_MODE", "LIVE_TRADING_ARMED", "KALSHI_DEMO")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def set_env(monkeypatch, **kv):
    for k, v in kv.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


# --- resolve_mode -----------------------------------------------------------

@pytest.mark.parametrize("requested_live,mode,armed,demo,expected", [
    # env can never upgrade a paper request
    (False, None,    None,       None,    PAPER),
    (False, "live",  ARM_PHRASE, None,    PAPER),
    (False, "live",  None,       None,    PAPER),
    # live requires the arm phrase
    (True,  None,    None,       None,    PAPER),
    (True,  None,    ARM_PHRASE, None,    LIVE),
    (True,  "live",  ARM_PHRASE, None,    LIVE),
    (True,  None,    ARM_PHRASE + "\n", None, LIVE),   # whitespace tolerated
    (True,  None,    ARM_PHRASE.lower(), None, PAPER), # exact phrase only
    # env vetoes
    (True,  "paper", ARM_PHRASE, None,    PAPER),
    (True,  None,    ARM_PHRASE, "true",  PAPER),
    (True,  None,    ARM_PHRASE, "1",     PAPER),
    (True,  None,    ARM_PHRASE, "false", LIVE),
    (True,  "bogus", ARM_PHRASE, None,    PAPER),
])
def test_resolve_mode(monkeypatch, requested_live, mode, armed, demo, expected):
    set_env(monkeypatch, TRADING_MODE=mode, LIVE_TRADING_ARMED=armed, KALSHI_DEMO=demo)
    assert resolve_mode(requested_live=requested_live) == expected


def test_live_requested_but_not_armed_raises(monkeypatch):
    set_env(monkeypatch, TRADING_MODE="live")
    with pytest.raises(LiveTradingNotArmed):
        resolve_mode(requested_live=True)


# --- KalshiClient wiring ----------------------------------------------------

def _no_http(monkeypatch):
    def boom(self, *a, **k):  # pragma: no cover - must never run
        raise AssertionError("HTTP call attempted")
    monkeypatch.setattr(KalshiClient, "_post", boom)


def test_demo_true_stays_demo_even_when_env_armed(monkeypatch):
    set_env(monkeypatch, TRADING_MODE="live", LIVE_TRADING_ARMED=ARM_PHRASE)
    c = KalshiClient(demo=True)
    assert c.demo is True and c.base_url == _DEMO


def test_demo_false_keeps_prod_host_for_reads_and_cancels(monkeypatch):
    c = KalshiClient(demo=False)
    assert c.demo is False and c.base_url == _PROD


def test_prod_place_order_blocked_when_not_armed(monkeypatch):
    _no_http(monkeypatch)
    c = KalshiClient(demo=False)
    with pytest.raises(LiveTradingNotArmed):
        c.place_order("KXTEST-1", yes_price=5)


def test_prod_place_order_allowed_when_armed(monkeypatch):
    set_env(monkeypatch, LIVE_TRADING_ARMED=ARM_PHRASE)
    captured = {}
    monkeypatch.setattr(KalshiClient, "_post", lambda self, path, body: captured.update(path=path, body=body) or {})
    KalshiClient(demo=False).place_order("KXTEST-1", yes_price=5)
    assert captured["path"] == "/portfolio/orders" and captured["body"]["yes_price"] == 5


def test_demo_place_order_never_gated(monkeypatch):
    monkeypatch.setattr(KalshiClient, "_post", lambda self, path, body: {"ok": True})
    assert KalshiClient(demo=True).place_order("KXTEST-1", yes_price=5) == {"ok": True}
