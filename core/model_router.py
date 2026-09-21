#!/usr/bin/env python3
"""
Model Router — Capability-based dynamic model resolution.
Configured via config/model_routing.yaml
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

logger = logging.getLogger("router")

@dataclass
class ModelEndpoint:
    name: str
    provider: str
    model: str
    api_key_env: str
    base_url: Optional[str] = None
    priority: int = 1
    max_retries: int = 3
    timeout: int = 30
    cost_per_1k: float = 0.0  # USD per 1k tokens

@dataclass
class CapabilityMapping:
    capability: str
    models: List[str]  # ordered by preference
    fallback: Optional[str] = None
    min_score: float = 0.0

class ModelRouter:
    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path or os.getenv('MODEL_ROUTING_CONFIG', 'config/model_routing.yaml'))
        self.endpoints: Dict[str, ModelEndpoint] = {}
        self.capabilities: Dict[str, CapabilityMapping] = {}
        self.telemetry: Dict[str, dict] = {}  # key: "tool:model", value: stats
        self._load_config()

    def _load_config(self):
        if not self.config_path.exists():
            logger.warning(f"Model routing config not found: {self.config_path}. Using defaults.")
            self._setup_defaults()
            return
        with open(self.config_path) as f:
            cfg = yaml.safe_load(f)
        # Load endpoints
        for name, ep in cfg.get('endpoints', {}).items():
            self.endpoints[name] = ModelEndpoint(
                name=name,
                provider=ep.get('provider', 'openrouter'),
                model=ep['model'],
                api_key_env=ep['api_key_env'],
                base_url=ep.get('base_url'),
                priority=ep.get('priority', 1),
                max_retries=ep.get('max_retries', 3),
                timeout=ep.get('timeout', 30),
                cost_per_1k=ep.get('cost_per_1k', 0.0),
            )
        # Load capability mappings
        for cap, mapping in cfg.get('capabilities', {}).items():
            self.capabilities[cap] = CapabilityMapping(
                capability=cap,
                models=mapping['models'],
                fallback=mapping.get('fallback'),
                min_score=mapping.get('min_score', 0.0),
            )
        logger.info(f"Loaded model router: {len(self.endpoints)} endpoints, {len(self.capabilities)} capabilities")

    def _setup_defaults(self):
        """Minimal default configuration if no YAML exists."""
        # Default: use OpenRouter with a generalist model
        self.endpoints['default'] = ModelEndpoint(
            name='default',
            provider='openrouter',
            model='openai/gpt-4o-mini',
            api_key_env='OPENROUTER_API_KEY',
            base_url='https://openrouter.ai/api/v1',
            cost_per_1k=0.00015,
        )
        self.capabilities['general'] = CapabilityMapping(
            capability='general',
            models=['default'],
            fallback='default',
        )

    def resolve(self, capability: str, requirements: Dict[str, Any] = None) -> ModelEndpoint:
        """
        Resolve a model endpoint for the requested capability.
        Tries models in order, returns first available (has API key).
        """
        if capability not in self.capabilities:
            logger.warning(f"Unknown capability: {capability}, falling back to 'general'")
            capability = 'general'
        mapping = self.capabilities[capability]
        for model_name in mapping.models:
            if model_name in self.endpoints:
                ep = self.endpoints[model_name]
                if self._has_api_key(ep):
                    logger.debug(f"Resolved capability '{capability}' to endpoint '{model_name}'")
                    return ep
        # Try fallback if defined
        if mapping.fallback and mapping.fallback in self.endpoints:
            ep = self.endpoints[mapping.fallback]
            if self._has_api_key(ep):
                logger.info(f"Using fallback '{mapping.fallback}' for capability '{capability}'")
                return ep
        # Ultimate fallback to 'default'
        if 'default' in self.endpoints:
            logger.warning(f"No configured model available for '{capability}'. Using default.")
            return self.endpoints['default']
        raise RuntimeError(f"No model endpoint available for capability '{capability}' and no default configured.")

    def _has_api_key(self, ep: ModelEndpoint) -> bool:
        key = os.getenv(ep.api_key_env)
        return key is not None and key.strip() != ''

    def record_telemetry(self, capability: str, model_name: str, success: bool, latency: float, tokens: int = 0, cost: float = 0.0):
        key = f"{capability}:{model_name}"
        if key not in self.telemetry:
            self.telemetry[key] = {
                'requests': 0,
                'successes': 0,
                'total_latency': 0.0,
                'total_tokens': 0,
                'total_cost': 0.0,
            }
        stats = self.telemetry[key]
        stats['requests'] += 1
        if success:
            stats['successes'] += 1
        stats['total_latency'] += latency
        stats['total_tokens'] += tokens
        stats['total_cost'] += cost

    def get_telemetry_report(self) -> Dict[str, dict]:
        report = {}
        for key, stats in self.telemetry.items():
            reqs = stats['requests']
            succ = stats['successes']
            report[key] = {
                'success_rate': succ / reqs if reqs else 0.0,
                'avg_latency': stats['total_latency'] / reqs if reqs else 0.0,
                'total_tokens': stats['total_tokens'],
                'total_cost': stats['total_cost'],
                'requests': reqs,
            }
        return report

    def save_telemetry(self, path: str = None):
        if path is None:
            path = 'logs/model_telemetry.json'
        p = Path(path)
        p.parent.mkdir(exist_ok=True)
        import json
        p.write_text(json.dumps(self.telemetry, indent=2))
