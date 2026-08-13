from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# A repeated free-text question that went to the AI bridge instead of a
# known command is a "gap" in what the assistant can do natively. This
# lifecycle tracks it from first sighting through to an enabled plugin:
#   collecting -> ready_for_generation -> (requires_review | pending_review)
#     -> enabled | generation_failed
#   collecting -> ... -> dismissed  (rejected by the user at any review step)
class GapCandidateStatus(str, Enum):
    COLLECTING = "collecting"
    READY_FOR_GENERATION = "ready_for_generation"
    GENERATION_FAILED = "generation_failed"
    REQUIRES_REVIEW = "requires_review"
    PENDING_REVIEW = "pending_review"
    ENABLED = "enabled"
    DISMISSED = "dismissed"


# Statuses where a new occurrence of a similar question should still be
# folded into this candidate rather than starting a new one.
OPEN_STATUSES = (
    GapCandidateStatus.COLLECTING,
    GapCandidateStatus.READY_FOR_GENERATION,
    GapCandidateStatus.REQUIRES_REVIEW,
)

SIMILARITY_THRESHOLD = 0.62
OCCURRENCE_THRESHOLD = 3
LOOKBACK_DAYS = 7


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass
class GapCandidate:
    representative_text: str
    status: GapCandidateStatus = GapCandidateStatus.COLLECTING
    id: int | None = None
    created_at: datetime | None = None
    last_seen: datetime | None = None
    generated_plugin_name: str | None = None
    generated_plugin_path: str | None = None
    safety_flags: list[str] = field(default_factory=list)
    error: str | None = None

    def suggestion_message(self) -> str:
        return (
            f"Я заметил, что ты часто просишь: «{self.representative_text}». "
            "Я подготовил плагин для этого, хочешь его включить?"
        )
