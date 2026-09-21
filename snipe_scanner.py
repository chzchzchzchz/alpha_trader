#!/usr/bin/env python3
"""
Weather snipe scanner — READ-ONLY. Places no orders, ever.

The edge being tested
---------------------
Kalshi's daily HIGH-temperature markets settle on the maximum temperature
recorded at one station over the local calendar day. That maximum is a RATCHET:
it only ever goes up. So the moment the observed temperature crosses a strike,
one side of that contract is mathematically locked — no forecast required, and
you do not have to wait for the afternoon peak.

    "79 or below"  -> dead the instant the station reads 80
    "86 or above"  -> won  the instant the station reads 86
    "84 to 85"     -> dead the instant the station reads 86

If the market still prices a locked contract at anything other than 0/100, the
difference is free money minus fees. This scanner measures how often that
happens and how big the gap is. It does NOT trade.

Two correctness details the previous versions got wrong
------------------------------------------------------
1. SETTLEMENT SOURCE. Kalshi settles these on "The Weather Company" readings
   for the climate site (e.g. CLINYC), not on api.weather.gov. We read NWS
   observations because they are free and public, but they can differ by ~1F
   from the settlement source. Every conclusion here carries that basis risk,
   so we require a safety margin before calling anything "locked".
2. DIRECTION. We parse `yes_sub_title` from the API ("86 or above", "84 to 85",
   "79 or below") instead of guessing direction from the ticker. Guessing the
   ticker is what made v21 directionally blind.

Usage:
    python3 snipe_scanner.py            # one pass over today's markets
    python3 snipe_scanner.py --watch    # re-scan every 10 minutes
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import time
from pathlib import Path

import requests
from zoneinfo import ZoneInfo

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
NWS = "https://api.weather.gov"
UA = {"User-Agent": "(kalshi weather research, chazispam@gmail.com)"}

# Kalshi temperature series -> (NWS station, IANA timezone, extreme)
#
# extreme="max": daily HIGH markets. max-so-far is an UPWARD ratchet.
# extreme="min": daily LOW markets.  min-so-far is a DOWNWARD ratchet.
#
# Use real IANA zones, not fixed UTC offsets: a hardcoded -4 for New York is
# EDT and silently becomes wrong every November, shifting the calendar-day
# boundary by an hour and corrupting which observations count toward today.
CITIES = {
    "KXHIGHNY":    ("KNYC", "America/New_York",    "max"),
    "KXHIGHCHI":   ("KMDW", "America/Chicago",     "max"),
    "KXHIGHLAX":   ("KLAX", "America/Los_Angeles", "max"),
    "KXHIGHMIA":   ("KMIA", "America/New_York",    "max"),
    "KXHIGHAUS":   ("KAUS", "America/Chicago",     "max"),
    "KXHIGHDEN":   ("KDEN", "America/Denver",      "max"),
    "KXHIGHPHIL":  ("KPHL", "America/New_York",    "max"),
    # Daily-low series. NOTE these are structurally riskier than highs: the
    # daily high is locked once afternoon cooling begins, but a new daily LOW
    # can still be set at 23:59 by an overnight front. The ratchet logic below
    # is still sound — it only ever locks a side that is already impossible to
    # reverse — but far fewer lows lock early in the day.
    "KXLOWTNY":    ("KNYC", "America/New_York",    "min"),
    "KXLOWTPHIL":  ("KPHL", "America/New_York",    "min"),
    "KXLOWTLAX":   ("KLAX", "America/Los_Angeles", "min"),
    "KXLOWTCHI":   ("KMDW", "America/Chicago",     "min"),
}

# Degrees of headroom required before we call an outcome "locked", to absorb
# disagreement between the NWS observation and the settlement source.
SAFETY_MARGIN_F = 1.0

def fee_for(price_cents: int, contracts: int = 1) -> int:
    """Kalshi fee in cents, rounded up to the next cent (minimum 1c)."""
    p = price_cents / 100.0
    raw = 0.07 * contracts * p * (1 - p)   # in dollars
    return max(1, math.ceil(raw * 100))


# ---------------------------------------------------------------- observations
def observed_extreme(station: str, tzname: str, extreme: str):
    """
    Most extreme temperature (F) observed at `station` so far during the local
    calendar day. extreme="max" for HIGH markets, "min" for LOW markets.
    """
    try:
        r = requests.get(f"{NWS}/stations/{station}/observations",
                         params={"limit": 300}, headers=UA, timeout=30)
        if r.status_code != 200:
            return None, None, 0
        feats = r.json().get("features", [])
    except Exception:
        return None, None, 0

    tz = ZoneInfo(tzname)
    today = dt.datetime.now(tz).date()
    todays = []
    for f in feats:
        p = f["properties"]
        c = (p.get("temperature") or {}).get("value")
        ts = p.get("timestamp")
        if c is None or not ts:
            continue
        local = dt.datetime.fromisoformat(ts).astimezone(tz)
        if local.date() != today:
            continue
        todays.append((c * 9 / 5 + 32, local))

    if not todays:
        return None, None, 0

    # OUTLIER GUARD.
    #
    # First attempt here dropped the single most extreme reading outright. That
    # was wrong: the daily peak is usually a genuine one-off sample (NY on
    # 2026-08-23 peaked at exactly one observation, 15:51 = 79.0F), so dropping
    # it discarded the very number we need and understated the max by ~1F.
    #
    # Instead, reject a reading only when it is physically implausible against
    # its own neighbours in time -- a real temperature curve is continuous, so
    # a true peak sits close to the samples on either side of it, while a
    # sensor glitch stands far apart from both.
    todays.sort(key=lambda x: x[1])          # chronological
    temps = [t for t, _ in todays]
    keep = []
    for i, (t, when) in enumerate(todays):
        neighbours = []
        if i > 0:
            neighbours.append(temps[i - 1])
        if i < len(todays) - 1:
            neighbours.append(temps[i + 1])
        # A lone sample more than 12F from EVERY neighbour is not weather.
        if neighbours and all(abs(t - nb) > 12.0 for nb in neighbours):
            continue
        keep.append((t, when))
    if not keep:
        keep = todays

    # A lone reading has no neighbours to be checked against, so the guard
    # above cannot vet it at all. That happens right after local midnight,
    # when only one observation exists for the new day. Refuse to report an
    # extreme from a single uncorroborated sample rather than let one ASOS
    # glitch declare a contract locked.
    if len(keep) < 2:
        return None, None, len(todays)

    best = max(keep, key=lambda x: x[0]) if extreme == "max" \
        else min(keep, key=lambda x: x[0])
    return best[0], best[1], len(todays)


# ------------------------------------------------------------------- contracts
def parse_condition(sub_title: str):
    """
    Turn Kalshi's yes_sub_title into a predicate on the final max temp.

    Returns (kind, lo, hi):
        ("above", X, None)  YES iff max >= X
        ("below", None, X)  YES iff max <= X
        ("range", A, B)     YES iff A <= max <= B
    """
    s = sub_title.strip().replace("°", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*or above$", s, re.I)
    if m:
        return "above", float(m.group(1)), None
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*or below$", s, re.I)
    if m:
        return "below", None, float(m.group(1))
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*to\s*(-?\d+(?:\.\d+)?)$", s, re.I)
    if m:
        return "range", float(m.group(1)), float(m.group(2))
    return None, None, None


def locked_side(kind, lo, hi, observed, extreme):
    """
    Is either side already mathematically settled?

    For extreme="max" the day's maximum is an UPWARD ratchet: it can still rise
    but can never fall. So anything the observed max has already achieved is
    permanent, and anything it has already exceeded is permanently exceeded.
    For extreme="min" the mirror holds downward.

    SAFETY_MARGIN_F is always applied so that MORE movement is required before
    we declare a lock -- never less. It absorbs disagreement between the NWS
    observation we read and The Weather Company reading Kalshi settles on.

    Returns "yes", "no", or None (not yet determined).
    """
    if extreme == "max":
        if kind == "above":
            # YES iff final_max >= lo. Reaching lo is permanent.
            return "yes" if observed >= lo + SAFETY_MARGIN_F else None
        if kind == "below":
            # YES iff final_max <= hi. Exceeding hi is permanent -> YES dead.
            return "no" if observed > hi + SAFETY_MARGIN_F else None
        if kind == "range":
            # YES iff lo <= final_max <= hi. Exceeding hi kills it permanently.
            # (Being below lo does NOT lock: the max can still climb into range.)
            return "no" if observed > hi + SAFETY_MARGIN_F else None
    else:  # extreme == "min": downward ratchet
        if kind == "below":
            # YES iff final_min <= hi. Dropping to hi is permanent.
            return "yes" if observed <= hi - SAFETY_MARGIN_F else None
        if kind == "above":
            # YES iff final_min >= lo. Dropping below lo is permanent -> dead.
            return "no" if observed < lo - SAFETY_MARGIN_F else None
        if kind == "range":
            # YES iff lo <= final_min <= hi. Dropping below lo kills it.
            return "no" if observed < lo - SAFETY_MARGIN_F else None
    return None


# ------------------------------------------------------------------- the scan
def scan(verbose=True):
    findings = []
    stamp = dt.datetime.now(dt.timezone.utc)

    for series, (station, tzname, extreme) in CITIES.items():
        mx, at, nobs = observed_extreme(station, tzname, extreme)
        if mx is None:
            if verbose:
                print(f"\n{series:12s} — no observations from {station}")
            continue

        try:
            r = requests.get(f"{KALSHI}/markets",
                             params={"series_ticker": series, "status": "open",
                                     "limit": 200}, timeout=30)
            markets = r.json().get("markets", []) if r.status_code == 200 else []
        except Exception:
            markets = []

        tz = ZoneInfo(tzname)
        # Match today's markets by EXACT date segment, never by substring.
        #
        # A previous version also tried an unpadded tag ("26AUG2") as a
        # belt-and-braces guard against zero-padding. That was actively
        # dangerous: "26AUG2" is a substring of "26AUG23", so on any
        # single-digit day the scanner swept in markets settling up to three
        # weeks later and tested TODAY's temperature against THEIR strikes --
        # manufacturing confident "LOCKED" calls on markets whose weather has
        # not happened yet. Ticker dates are always zero-padded; parse the
        # segment and compare it whole.
        now_local = dt.datetime.now(tz)
        today_tag = now_local.strftime("%y%b%d").upper()

        def is_today(mkt):
            parts = mkt.get("ticker", "").split("-")
            return len(parts) >= 2 and parts[1].upper() == today_tag

        todays = [m for m in markets if is_today(m)]

        if verbose:
            print(f"\n{series:12s} {station}  {extreme} so far {mx:.1f}F"
                  f" at {at.strftime('%H:%M') if at else '?'}"
                  f"  ({nobs} obs, {len(todays)} live markets)")

        for m in todays:
            kind, lo, hi = parse_condition(m.get("yes_sub_title", ""))
            if kind is None:
                continue
            side = locked_side(kind, lo, hi, mx, extreme)
            if side is None:
                continue

            # Take prices straight from the API rather than deriving them.
            # 100 - yes_bid does equal no_ask today, but reading the field the
            # exchange publishes removes a standing assumption about how the
            # two books relate.
            if side == "yes":
                px = m.get("yes_ask_dollars")
                depth = m.get("yes_ask_size_fp")
            else:
                px = m.get("no_ask_dollars")
                depth = m.get("yes_bid_size_fp")
            if px is None:
                continue
            cost = int(round(float(px) * 100))
            if cost <= 0 or cost >= 100:
                continue

            # DEPTH GATE. Kalshi publishes size 0 on empty sides of the book.
            # Without this, a "locked, +97c profit" line can be an order that
            # cannot be filled at any size -- the most seductive kind of fake
            # opportunity, because it always shows the biggest edge.
            try:
                depth_n = float(depth) if depth is not None else 0.0
            except (TypeError, ValueError):
                depth_n = 0.0
            if depth_n < 1:
                continue

            f = fee_for(cost)
            profit = 100 - cost - f
            if profit <= 0:
                continue

            findings.append({
                "ts": stamp.isoformat(),
                "ticker": m["ticker"],
                "condition": m.get("yes_sub_title", ""),
                "station": station,
                "observed_f": round(mx, 1),
                "extreme": extreme,
                "locked_side": side,
                "cost_cents": cost,
                "fee_cents": f,
                "profit_cents": profit,
                "roi_pct": round(100 * profit / cost, 1),
                "depth": depth_n,
                "volume_24h": m.get("volume_24h_fp"),
                "close_time": m.get("close_time"),
            })
            if verbose:
                print(f"    LOCKED {side.upper():3s} {m['ticker']:30s}"
                      f" [{m.get('yes_sub_title',''):14s}] cost={cost:3d}c"
                      f" fee={f}c -> +{profit}c  ROI {100*profit/cost:.0f}%"
                      f"  depth={depth}")

    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="rescan every 10 min")
    ap.add_argument("--interval", type=int, default=600)
    args = ap.parse_args()

    out = Path(__file__).parent / "logs" / "snipe_findings.jsonl"
    out.parent.mkdir(exist_ok=True)

    while True:
        print("=" * 78)
        print(f"SNIPE SCAN  {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}"
              f"   (read-only, places no orders)")
        print("=" * 78)
        found = scan()
        print()
        if found:
            best = max(found, key=lambda x: x["profit_cents"])
            total = sum(f["profit_cents"] for f in found)
            print(f"{len(found)} locked mispricing(s). "
                  f"Best: {best['ticker']} +{best['profit_cents']}c "
                  f"({best['roi_pct']}% ROI). Sum if all filled 1x: +{total}c")
            with out.open("a") as fh:
                for f in found:
                    fh.write(json.dumps(f) + "\n")
            print(f"appended to {out}")
        else:
            print("No locked mispricings right now — "
                  "either nothing is settled yet, or the book already reflects it.")

        if not args.watch:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
