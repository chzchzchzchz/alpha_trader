"""
LangGraph Macro Cycle Engine — agent package.

Sub-packages:
  analysts/    — cycle economist, sentiment reader, sector specialist
  researchers/ — leading & lagging indicator researchers
  managers/    — portfolio vault
  trader/      — trade executor

Public entry-point:
  from agents.graph import build_macro_graph
"""
from agents.graph import build_macro_graph
from agents.state import MacroCycleState

__all__ = ["build_macro_graph", "MacroCycleState"]
