#!/usr/bin/env python3
"""
StrategyOrchestrator — load all strategies, generate signals, allocate capital.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger("orchestrator")

@dataclass
class UnifiedSignal:
    ticker: str
    strategy: str
    side: str  # 'yes' or 'no'
    price: float
    score: float
    edge: float
    confidence: float = 1.0
    urgency: float = 0.0
    reason: str = ""

class StrategyOrchestrator:
    def __init__(self, client, analyzer, swarm=None, capital: float = 500.0):
        self.client = client
        self.analyzer = analyzer
        self.swarm = swarm
        self.capital = capital
        self.strategies: Dict[str, Any] = {}
        self._load_all_strategies()

    def _load_all_strategies(self):
        import sys
        strat_dir = Path(__file__).parent / "strategies"
        allowed = [
            'near_zero', 'category_specialist', 'convergence',
            'late_window', 'flash_crash', 'longshot',
            'overreaction_reversal', 'panic_sniper', 'smart_money', 'time_sniper'
        ]
        for file in strat_dir.glob("*.py"):
            if file.stem.startswith('_') or file.stem not in allowed:
                continue
            try:
                spec = importlib.util.spec_from_file_location(file.stem, file)
                if spec is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                # Critical: add to sys.modules BEFORE executing to preserve __dict__
                sys.modules[file.stem] = module
                spec.loader.exec_module(module)
                # Find strategy class: CamelCase of filename or explicit
                class_name = ''.join([p.capitalize() for p in file.stem.split('_')]) + 'Strategy'
                strat_cls = getattr(module, class_name, None)
                if strat_cls:
                    # Instantiate with client and analyzer (most need both)
                    strat = strat_cls(client=self.client, analyzer=self.analyzer)
                    self.strategies[file.stem] = strat
                    logger.info(f"Loaded strategy: {file.stem} -> {class_name}")
                else:
                    logger.warning(f"Strategy file {file.stem} missing class {class_name}")
            except Exception as e:
                logger.error(f"Failed to load strategy {file.stem}: {e}", exc_info=True)

    def generate_signals(self, markets: List) -> List[UnifiedSignal]:
        all_signals = []
        for strat_name, strat in self.strategies.items():
            try:
                if hasattr(strat, 'run_scan'):
                    opps = strat.run_scan()
                elif hasattr(strat, 'generate_signals'):
                    opps = strat.generate_signals(markets)
                else:
                    continue
                for opp in opps:
                    if not isinstance(opp, dict):
                        continue
                    ticker = opp.get('ticker', '')
                    side = opp.get('side', 'yes')
                    price = opp.get('price', opp.get('entry_price', 0.0))
                    score = opp.get('score', 0.0)
                    edge = opp.get('edge', score)
                    reason = opp.get('title', '')
                    if ticker and score > 0:
                        sig = UnifiedSignal(
                            ticker=ticker,
                            strategy=strat_name,
                            side=side,
                            price=price,
                            score=score,
                            edge=edge,
                            reason=reason,
                        )
                        all_signals.append(sig)
            except Exception as e:
                logger.error(f"Strategy {strat_name} failed: {e}", exc_info=True)
        # Deduplicate by ticker, keep highest score
        seen = {}
        deduped = []
        for sig in sorted(all_signals, key=lambda s: s.score, reverse=True):
            if sig.ticker not in seen:
                seen[sig.ticker] = sig
                deduped.append(sig)
        logger.info(f"Generated {len(deduped)} unique signals from {len(all_signals)} raw")
        return deduped

    def allocate_capital(self, signals: List[UnifiedSignal], total_capital: float, risk_manager=None) -> Dict[str, dict]:
        if not signals:
            return {}
        # Simple fixed-per-signal allocation to ensure orders
        base_allocation_usd = total_capital * 0.05  # 5% of capital per signal max
        allocations = {}
        for sig in signals[:10]:
            price = sig.price
            if price <= 0:
                continue
            # Basic contracts = floor(allocation_usd / price)
            contracts = int(base_allocation_usd / price)
            if contracts == 0:
                # If price is very low, we can afford at least 1
                contracts = 1 if price <= total_capital else 0
            if contracts > 0:
                allocations[sig.ticker] = {
                    'contracts': contracts,
                    'side': sig.side,
                    'price': sig.price,
                    'strategy': sig.strategy,
                    'edge': sig.edge,
                    'score': sig.score,
                    'kelly': 0.05,
                }
        # Apply risk filter if provided
        if risk_manager and hasattr(risk_manager, 'filter_allocs'):
            allocations = risk_manager.filter_allocs(allocations)
        total_contracts = sum(v['contracts'] for v in allocations.values())
        logger.info(f"Allocated {len(allocations)} tickers, total contracts {total_contracts}")
        return allocations
