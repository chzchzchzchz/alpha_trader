#!/usr/bin/env python3
"""
Risk Manager — enforce position sizing and exposure limits.
"""

from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger("risk")

class RiskManager:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.capital = orchestrator.capital
        # Configurable limits (could move to config)
        self.max_total_exposure = self.capital * 0.5   # No more than 50% deployed
        self.max_per_ticker = self.capital * 0.10     # No more than 10% per ticker
        self.max_per_strategy = self.capital * 0.20   # No more than 20% per strategy
        self.max_total_contracts = 1000               # Hard cap

    def filter_allocs(self, allocations: dict) -> dict:
        if not allocations:
            return {}
        # Compute notional value of each allocation
        notional_by_ticker = {}
        notional_by_strategy = defaultdict(float)
        total_notional = 0.0
        for ticker, alloc in allocations.items():
            notional = alloc['contracts'] * alloc['price']
            notional_by_ticker[ticker] = notional
            notional_by_strategy[alloc['strategy']] += notional
            total_notional += notional

        logger.debug(f"Risk check: total_notional=${total_notional:.2f} cap=${self.max_total_exposure:.2f}")

        # Apply total exposure cap
        if total_notional > self.max_total_exposure:
            scale = self.max_total_exposure / total_notional
            logger.warning(f"Scale down allocations by {scale:.2%} to respect total exposure cap")
            for ticker in allocations:
                allocations[ticker]['contracts'] = max(1, int(allocations[ticker]['contracts'] * scale))

        # Apply per-ticker caps
        for ticker, alloc in list(allocations.items()):
            notional = alloc['contracts'] * alloc['price']
            if notional > self.max_per_ticker:
                new_contracts = int(self.max_per_ticker / alloc['price'])
                if new_contracts < 1:
                    logger.info(f"Removing {ticker} - exceeds per-ticker cap")
                    del allocations[ticker]
                else:
                    old = alloc['contracts']
                    alloc['contracts'] = min(alloc['contracts'], new_contracts)
                    logger.debug(f"Reduced {ticker} contracts {old}->{alloc['contracts']} due to per-ticker cap")

        # Apply per-strategy caps
        strat_totals = defaultdict(float)
        for alloc in allocations.values():
            strat_totals[alloc['strategy']] += alloc['contracts'] * alloc['price']
        for strategy, total in strat_totals.items():
            if total > self.max_per_strategy:
                # Reduce allocations for this strategy proportionally
                excess = total - self.max_per_strategy
                strat_allocs = [(t, a) for t, a in allocations.items() if a['strategy'] == strategy]
                # Sort by score descending, reduce lower score ones first
                strat_allocs.sort(key=lambda x: x[1]['score'], reverse=True)
                for ticker, alloc in strat_allocs:
                    notional = alloc['contracts'] * alloc['price']
                    if excess <= 0:
                        break
                    if notional <= excess:
                        excess -= notional
                        del allocations[ticker]
                        logger.debug(f"Removed {ticker} from {strategy} to respect per-strategy cap")
                    else:
                        new_contracts = int((notional - excess) / alloc['price'])
                        if new_contracts < 1:
                            del allocations[ticker]
                        else:
                            alloc['contracts'] = new_contracts
                        excess = 0
                        logger.debug(f"Reduced {ticker} in {strategy} to respect per-strategy cap")

        # Global contracts cap
        total_contracts = sum(a['contracts'] for a in allocations.values())
        if total_contracts > self.max_total_contracts:
            excess = total_contracts - self.max_total_contracts
            # Reduce smallest allocations first
            sorted_allocs = sorted(allocations.items(), key=lambda x: x[1]['contracts'])
            for ticker, alloc in sorted_allocs:
                if excess <= 0:
                    break
                take = min(alloc['contracts'], excess)
                alloc['contracts'] -= take
                excess -= take
                if alloc['contracts'] == 0:
                    del allocations[ticker]
            logger.warning(f"Applied total contracts cap, reduced by {excess}")

        return allocations
