"""AGENTIC STAR Marketplace entrypoint for EDU-C2-025."""

from pathlib import Path
from typing import Any

from framework.utils.config_loader import load_agent_config
from shared.bootstrap.marketplace_app import run_agent_marketplace

from src.graph.graph import ComplianceTrainingCompletionTrackingGapReportAgent

extend_config: dict[str, Any] = {}

if __name__ == "__main__":
    run_agent_marketplace(
        ComplianceTrainingCompletionTrackingGapReportAgent,
        agent_name="ComplianceTrainingCompletionTrackingGapReportAgent",
        namespace="EDU",
        config={**load_agent_config(Path(__file__).resolve().parent), **extend_config},
    )
