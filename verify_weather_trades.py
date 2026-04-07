#!/usr/bin/env python3
"""Analyze weather oracle trades vs actual NOAA forecasts."""
forecasts = {
    "NY_2026-04-07": {"high": 51, "low": 33},
    "PHIL_2026-04-07": {"high": 54, "low": 31},
    "LAX_2026-04-07": {"high": 74, "low": 57},
    "LAX_2026-04-06": {"high": None, "low": 56},
}

trades = [
    ("KXHIGHNY-26APR07-T55", "yes", 3, "2026-04-07", "NY", "Will high >55?", "56° or above"),
    ("KXHIGHNY-26APR07-T48", "yes", 2, "2026-04-07", "NY", "Will high <48?", "47° or below"),
    ("KXHIGHNY-26APR07-B54.5", "yes", 15, "2026-04-07", "NY", "Will high 54-55?", "54° to 55°"),
    ("KXHIGHNY-26APR07-B48.5", "yes", 5, "2026-04-07", "NY", "Will high 48-49?", "48° to 49°"),
    ("KXLOWTPHIL-26APR07-T41", "yes", 7, "2026-04-07", "PHIL", "Will low >41?", "41° or above"),
    ("KXLOWTPHIL-26APR07-T34", "yes", 17, "2026-04-07", "PHIL", "Will low >34?", "34° or above"),
    ("KXLOWTPHIL-26APR07-B40.5", "yes", 17, "2026-04-07", "PHIL", "Will low 40-41.5?", "40° to 41°"),
    ("KXLOWTPHIL-26APR07-B38.5", "yes", 24, "2026-04-07", "PHIL", "Will low 38-39.5?", "38° to 39°"),
    ("KXLOWTPHIL-26APR07-B36.5", "yes", 29, "2026-04-07", "PHIL", "Will low 36-37.5?", "36° to 37°"),
    ("KXLOWTPHIL-26APR07-B34.5", "yes", 18, "2026-04-07", "PHIL", "Will low 34-35.5?", "34° to 35°"),
    ("KXLOWTLAX-26APR07-T51", "yes", 2, "2026-04-07", "LAX", "Will low >51?", "51° or above"),
    ("KXLOWTLAX-26APR07-B55.5", "yes", 16, "2026-04-07", "LAX", "Will low 55-56?", "55° to 56°"),
    ("KXLOWTLAX-26APR07-B53.5", "yes", 4, "2026-04-07", "LAX", "Will low 53-54?", "53° to 54°"),
    ("KXLOWTLAX-26APR07-B51.5", "yes", 3, "2026-04-07", "LAX", "Will low 51-52?", "51° to 52°"),
    ("KXLOWTLAX-26APR06-T53", "yes", 2, "2026-04-06", "LAX", "Will low >53?", "53° or above"),
    ("KXLOWTLAX-26APR06-B57.5", "yes", 3, "2026-04-06", "LAX", "Will low 57-58?", "57° to 58°"),
    ("KXLOWTLAX-26APR06-B55.5", "yes", 15, "2026-04-06", "LAX", "Will low 55-56?", "55° to 56°"),
]

print("=== TRADE VERIFICATION vs NOAA Forecasts ===")
print(f"{'Ticker':45s} {'Side':4s} Cost | NWS  | Contract Says          | NOAA Says  | Result")
print("-"*90)

wins = 0
losses = 0
total_cost = 0
total_payout = 0

for ticker, side, cost, date, city, title, yes_label in trades:
    key = f"{city}_{date}"
    fc = forecasts.get(key, {})
    parts = ticker.split("-")
    
    is_low = "LOW" in ticker
    temp = fc.get("low" if is_low else "high")
    temp_str = f"{temp}°F" if temp else "N/A"
    
    # The weather oracle bought "YES" on these.
    # YES = "the range/threshold described in yes_label happens"
    # Check if NOAA forecast falls in the YES range
    will_yes = False
    if temp is not None:
        import re
        nums = re.findall(r'(\d+)', yes_label)
        if "above" in yes_label and nums:
            threshold = int(nums[0])
            will_yes = temp >= threshold
        elif "below" in yes_label and nums:
            threshold = int(nums[0])
            will_yes = temp <= threshold
        elif "to" in yes_label and len(nums) >= 2:
            low_t = int(nums[0])
            high_t = int(nums[1])
            will_yes = low_t <= temp <= high_t
    
    result = "WIN" if (side == "yes" and will_yes) else "LOSE"
    if result == "WIN":
        wins += 1
        payout = 100
        total_payout += payout
    else:
        losses += 1
        total_cost += cost

print(f"  {ticker:45s} {side:4s} {cost:3d}c | {temp_str:5s} | {yes_label:22s} | {temp_str:5s} | {result}")

print(f"\n=== SUMMARY ===")
print(f"Wins: {wins}   Losses: {losses}")
print(f"Total potential payout: ${total_payout/100:.2f}")
print(f"Total cost of losers: ${total_cost/100:.2f}")
print(f"Net if all settle now: ${(total_payout - total_cost)/100:.2f}")
print(f"Net cost so far: ${total_cost/100:.2f} (invested)")
