from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.message_bus import MessageBus, message_bus
from modules.plugin_agent.domain import (
    LOOKBACK_DAYS,
    OCCURRENCE_THRESHOLD,
    SIMILARITY_THRESHOLD,
    GapCandidate,
    GapCandidateStatus,
    normalize,
    similarity,
)
from modules.plugin_agent.events import PluginCandidateReadyForReview
from modules.plugin_agent.uow import PluginAgentUnitOfWork

logger = get_logger(__name__)


@dataclass
class RecordResult:
    candidate_id: int
    occurrence_count: int
    promoted: bool


def record_question(uow: PluginAgentUnitOfWork, raw_text: str) -> RecordResult | None:
    """Folds a free-text question into an existing similar candidate or
    starts a new one, and promotes it to the generation queue once it has
    recurred `OCCURRENCE_THRESHOLD` times within `LOOKBACK_DAYS` days.
    Returns None for text too short to be meaningful, or that already
    matches a loaded plugin (checked by the caller via
    modules.plugin_agent.plugin_loader.match_command before publishing the
    event, so this function stays free of that dependency)."""
    normalized = normalize(raw_text)
    if not normalized or len(normalized) < 4:
        return None

    now = datetime.now(timezone.utc)
    with uow:
        open_candidates = uow.candidates.list_open()
        best_candidate: GapCandidate | None = None
        best_score = 0.0
        for candidate in open_candidates:
            score = similarity(normalized, normalize(candidate.representative_text))
            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate is not None and best_score >= SIMILARITY_THRESHOLD:
            candidate = best_candidate
            candidate.last_seen = now
            uow.candidates.update(candidate)
        else:
            candidate = GapCandidate(representative_text=raw_text.strip(), created_at=now, last_seen=now)
            candidate.id = uow.candidates.add(candidate)

        assert candidate.id is not None
        uow.candidates.record_event(candidate.id, raw_text.strip(), now)

        cutoff = now - timedelta(days=LOOKBACK_DAYS)
        occurrence_count = uow.candidates.count_recent_events(candidate.id, cutoff)

        promoted = False
        if candidate.status == GapCandidateStatus.COLLECTING and occurrence_count >= OCCURRENCE_THRESHOLD:
            candidate.status = GapCandidateStatus.READY_FOR_GENERATION
            uow.candidates.update(candidate)
            promoted = True

        uow.commit()

    if promoted:
        logger.info(
            "Gap candidate #%s promoted to generation queue after %d occurrences in %d days: %r",
            candidate.id,
            occurrence_count,
            LOOKBACK_DAYS,
            normalized[:80],
        )

    return RecordResult(candidate_id=candidate.id, occurrence_count=occurrence_count, promoted=promoted)


def list_candidates(uow: PluginAgentUnitOfWork, status: GapCandidateStatus | None = None) -> list[GapCandidate]:
    with uow:
        return uow.candidates.list_by_status(status)


def get_candidate(uow: PluginAgentUnitOfWork, candidate_id: int) -> GapCandidate | None:
    with uow:
        return uow.candidates.get(candidate_id)


def get_generated_code(uow: PluginAgentUnitOfWork, candidate_id: int) -> str:
    candidate = get_candidate(uow, candidate_id)
    if candidate is None or not candidate.generated_plugin_path:
        raise ValueError(f"No generated plugin found for suggestion '{candidate_id}'")
    path = Path(candidate.generated_plugin_path)
    if not path.is_file():
        raise ValueError("Generated plugin file no longer exists")
    return path.read_text(encoding="utf-8")


def approve(
    uow: PluginAgentUnitOfWork, candidate_id: int, registry: Any, plugins_dir: Path
) -> tuple[str, Path]:
    """Moves the generated file from _pending/ into the live plugins dir,
    loads+registers it on the given PluginRegistry, and marks the candidate
    enabled. Raises ValueError (caller turns this into a dispatcher FAILED
    response) if there's nothing to approve or the plugin fails to load."""
    with uow:
        candidate = uow.candidates.get(candidate_id)
        if candidate is None or not candidate.generated_plugin_path:
            raise ValueError(f"No generated plugin found for suggestion '{candidate_id}'")

        source = Path(candidate.generated_plugin_path)
        if not source.is_file():
            raise ValueError("Generated plugin file no longer exists")

        destination = plugins_dir / source.name
        shutil.move(str(source), str(destination))

        loaded = registry.load_file(destination)
        if loaded is None:
            destination.unlink(missing_ok=True)
            candidate.status = GapCandidateStatus.GENERATION_FAILED
            candidate.error = "Plugin failed validation on enable"
            uow.candidates.update(candidate)
            uow.commit()
            raise ValueError("Generated plugin failed validation and was not enabled")

        registry.register(loaded)
        candidate.status = GapCandidateStatus.ENABLED
        candidate.generated_plugin_path = str(destination)
        uow.candidates.update(candidate)
        uow.commit()

    logger.info("Plugin suggestion #%s enabled as command '%s'", candidate_id, loaded.name)
    return loaded.name, destination


def reject(uow: PluginAgentUnitOfWork, candidate_id: int) -> None:
    with uow:
        candidate = uow.candidates.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Unknown suggestion '{candidate_id}'")

        if candidate.generated_plugin_path:
            Path(candidate.generated_plugin_path).unlink(missing_ok=True)

        candidate.status = GapCandidateStatus.DISMISSED
        uow.candidates.update(candidate)
        uow.commit()
    logger.info("Plugin suggestion #%s dismissed by user", candidate_id)


async def process_next_ready_candidate(
    uow: PluginAgentUnitOfWork, bus: MessageBus = message_bus
) -> None:
    """One iteration of GapPromotionWorker's poll loop: takes the oldest
    'ready_for_generation' candidate (if any) and runs the AI plugin
    generator on it. Imports plugin_generator lazily, same as the original
    code, so a broken/uninstalled generation dependency doesn't prevent
    gap-tracking itself from working. `async` (mirroring
    modules.calendar.service_layer.check_due_reminders' shape) only because
    publishing PluginCandidateReadyForReview at the bottom needs it — the
    actual generation call itself is synchronous."""
    from modules.plugin_agent.plugin_generator import generate_plugin_for_candidate

    with uow:
        ready = uow.candidates.list_by_status(GapCandidateStatus.READY_FOR_GENERATION)
    if not ready:
        return

    candidate = ready[0]
    assert candidate.id is not None
    logger.info("Generating plugin for gap candidate #%s", candidate.id)
    try:
        result = generate_plugin_for_candidate(
            {"id": candidate.id, "representative_text": candidate.representative_text}
        )
    except Exception:
        logger.exception("Plugin generation crashed for candidate #%s", candidate.id)
        candidate.status = GapCandidateStatus.GENERATION_FAILED
        candidate.error = "Generation crashed; see logs for the traceback."
        with uow:
            uow.candidates.update(candidate)
            uow.commit()
        return

    if not result.success:
        logger.error("Plugin generation failed for candidate #%s: %s", candidate.id, result.error)
        candidate.status = GapCandidateStatus.GENERATION_FAILED
        candidate.error = result.error or ""
        with uow:
            uow.candidates.update(candidate)
            uow.commit()
        return

    safety_flags = result.safety_report.flags if result.safety_report else []
    candidate.status = (
        GapCandidateStatus.REQUIRES_REVIEW if safety_flags else GapCandidateStatus.PENDING_REVIEW
    )
    candidate.generated_plugin_name = result.plugin_name
    candidate.generated_plugin_path = str(result.plugin_path)
    candidate.safety_flags = safety_flags
    candidate.error = None
    with uow:
        uow.candidates.update(candidate)
        uow.commit()
    logger.info(
        "Plugin candidate #%s generated -> %s (status=%s, flags=%d)",
        candidate.id,
        result.plugin_name,
        candidate.status.value,
        len(safety_flags),
    )
    await bus.publish(
        PluginCandidateReadyForReview(
            candidate_id=candidate.id,
            plugin_name=result.plugin_name,
            requires_manual_review=bool(safety_flags),
        )
    )
