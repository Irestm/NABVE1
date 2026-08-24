from __future__ import annotations

from dataclasses import dataclass, field

from modules.ui_automation.domain import UIStep

# Wall-clock step cap per voice task (see runner.py's loop) — the agreed
# 12-15 range from AGENT_NOTES.md's plan, picked at the high end since each
# free/read step is cheap and the RPM throttle already bounds wall time.
MAX_STEPS = 15

# Half of modules.ai_bridge.api_providers.GEMINI_RPM_LIMIT (6) — the agreed
# "twice as strict" margin for the riskiest feature in the project. Checked
# against the same shared modules.ai_bridge.quota_tracker counter every other
# Gemini caller uses, just with a lower ceiling.
OS_AGENT_RPM_LIMIT = 3

DECISION_KINDS = ("step", "done", "stuck")


@dataclass(frozen=True)
class AgentDecision:
    """One iteration's verdict from planner.decide_next(). `step`/`reason` is
    set depending on `kind`: "step" carries a UIStep to run or queue, "done"
    carries a spoken summary in `reason` (task complete, nothing left to do),
    "stuck" carries a spoken explanation in `reason` (model couldn't find a
    way forward) — mirrors modules.ui_automation.domain.UIStep's own
    field-depends-on-kind shape, enforced by planner._parse_decision, not by
    this dataclass itself."""

    kind: str
    step: UIStep | None = None
    reason: str | None = None


@dataclass
class AgentSession:
    """One task's worth of state, local to a single runner.run_task() call —
    NOT the module-level "is agent mode on" flag (see session.py for that).
    `journal` is spoken-language, human-readable entries for both the
    planner's own next-step context and the optional post-hoc "why"
    explanation; `pending` is the write-tier queue nothing has touched on
    screen yet — see modules/os_agent/safety.py for what lands here vs
    executes immediately."""

    task: str
    journal: list[str] = field(default_factory=list)
    pending: list[UIStep] = field(default_factory=list)
    outcome: str = "limit"  # "done" | "stuck" | "limit" | "throttled"
    summary: str | None = None
