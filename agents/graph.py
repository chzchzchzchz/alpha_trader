"""
LangGraph StateGraph for the Macro Cycle Engine.

Pipeline (left to right):
  leading_indicators  ──┐
                        ├──► cycle_economist ──┐
  lagging_indicators  ──┘                      │
                         sentiment_reader ──────┤
                                                │
                                       sector_specialist
                                                │
                                       portfolio_vault
                                                │
                                       trader_executor
                                                │
                                             END

Researchers run in parallel (both write disjoint keys), then analysts
run in series, followed by the manager and executor.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, END

from agents.state import MacroCycleState
from agents.researchers.leading_indicators import leading_indicators_node
from agents.researchers.lagging_indicators import lagging_indicators_node
from agents.analysts.cycle_economist import cycle_economist_node
from agents.analysts.sentiment_reader import sentiment_reader_node
from agents.analysts.sector_specialist import sector_specialist_node
from agents.managers.portfolio_vault import portfolio_vault_node
from agents.trader.executor import trader_executor_node


def build_macro_graph():
    """
    Build and compile the Macro Cycle Engine StateGraph.

    Returns a compiled LangGraph app that accepts a MacroCycleState dict
    and returns the final state after all nodes have run.

    Usage::

        graph = build_macro_graph()
        final_state = graph.invoke({})
        print(final_state["run_summary"])
    """
    builder = StateGraph(MacroCycleState)

    # ── Register nodes ────────────────────────────────────────────────
    builder.add_node("leading_indicators", leading_indicators_node)
    builder.add_node("lagging_indicators", lagging_indicators_node)
    builder.add_node("cycle_economist",    cycle_economist_node)
    builder.add_node("sentiment_reader",   sentiment_reader_node)
    builder.add_node("sector_specialist",  sector_specialist_node)
    builder.add_node("portfolio_vault",    portfolio_vault_node)
    builder.add_node("trader_executor",    trader_executor_node)

    # ── Entry point: both researchers run after START ─────────────────
    builder.set_entry_point("leading_indicators")

    # leading_indicators → lagging_indicators (sequential so lagging can
    # merge its FRED data into the existing snapshot from leading)
    builder.add_edge("leading_indicators", "lagging_indicators")

    # After both researchers complete, run analysts
    builder.add_edge("lagging_indicators", "cycle_economist")
    builder.add_edge("lagging_indicators", "sentiment_reader")

    # Both analysts feed into sector specialist
    builder.add_edge("cycle_economist",  "sector_specialist")
    builder.add_edge("sentiment_reader", "sector_specialist")

    # Sector specialist → vault → executor → END
    builder.add_edge("sector_specialist", "portfolio_vault")
    builder.add_edge("portfolio_vault",   "trader_executor")
    builder.add_edge("trader_executor",   END)

    return builder.compile()
