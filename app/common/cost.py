"""In-memory cost tracker for Claude Agent SDK usage."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentCostSummary:
    """Accumulated cost data for a single agent."""

    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    executions: int = 0
    last_execution_at: float = 0.0


class CostTracker:
    """Singleton tracker that accumulates Claude Agent SDK costs per agent.

    Thread-safe for asyncio (single-threaded event loop).
    Records are kept in memory only — resets on restart.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentCostSummary] = {}

    def record(
        self,
        agent_name: str,
        cost_usd: float | None,
        usage: dict[str, Any] | None,
        card_id: str = "",
    ) -> None:
        """Record cost from a single SDK execution."""
        if agent_name not in self._agents:
            self._agents[agent_name] = AgentCostSummary()

        summary = self._agents[agent_name]
        summary.executions += 1
        summary.last_execution_at = time.time()

        if cost_usd is not None:
            summary.total_cost_usd += cost_usd

        if usage:
            summary.total_input_tokens += usage.get("input_tokens", 0)
            summary.total_output_tokens += usage.get("output_tokens", 0)

        logger.info(
            "Cost tracked for %s%s: $%.4f | input=%d output=%d | cumulative=$%.4f over %d executions",
            agent_name,
            f" (card {card_id})" if card_id else "",
            cost_usd or 0.0,
            usage.get("input_tokens", 0) if usage else 0,
            usage.get("output_tokens", 0) if usage else 0,
            summary.total_cost_usd,
            summary.executions,
        )

    def get_summary(self) -> dict[str, dict[str, Any]]:
        """Return cost summary for all agents."""
        return {
            name: {
                "total_cost_usd": round(summary.total_cost_usd, 4),
                "total_input_tokens": summary.total_input_tokens,
                "total_output_tokens": summary.total_output_tokens,
                "executions": summary.executions,
                "last_execution_at": summary.last_execution_at,
            }
            for name, summary in self._agents.items()
        }

    def get_totals(self) -> dict[str, Any]:
        """Return aggregate totals across all agents."""
        total_cost = sum(s.total_cost_usd for s in self._agents.values())
        total_input = sum(s.total_input_tokens for s in self._agents.values())
        total_output = sum(s.total_output_tokens for s in self._agents.values())
        total_executions = sum(s.executions for s in self._agents.values())
        return {
            "total_cost_usd": round(total_cost, 4),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_executions": total_executions,
        }


# Module-level singleton
cost_tracker = CostTracker()
