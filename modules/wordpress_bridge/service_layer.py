from __future__ import annotations

import uuid

from core.logger import get_logger
from modules.wordpress_bridge import content_processor, php_fixer, wp_draft_publisher
from modules.wordpress_bridge.domain import UploadJob, UploadJobStatus

logger = get_logger(__name__)

# In-memory only, deliberately: a job is a single upload-to-draft run that
# takes well under a minute end to end (see wp_draft_publisher.py) — there
# is nothing here that needs to survive a backend restart, unlike
# modules.plugin_agent's GapCandidate rows, which accumulate over days.
_jobs: dict[str, UploadJob] = {}


def create_job(site_url: str) -> UploadJob:
    job = UploadJob(job_id=uuid.uuid4().hex, site_url=site_url)
    _jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> UploadJob | None:
    return _jobs.get(job_id)


async def run_upload_job(job_id: str, file_paths: list[str], *, rewrite_with_ai: bool = False) -> None:
    job = _jobs.get(job_id)
    if job is None:
        logger.error("run_upload_job called with unknown job_id=%s", job_id)
        return

    job.status = UploadJobStatus.PROCESSING
    try:
        draft = content_processor.build_draft_content(file_paths)
        if rewrite_with_ai:
            draft.html_body = await content_processor.rewrite_html_for_blog(draft.html_body)

        result = await wp_draft_publisher.publish_draft(job.site_url, draft)

        job.status = UploadJobStatus.DRAFT_READY
        job.edit_url = result.edit_url
        job.message = (
            f'Черновик «{result.title}» готов и ждёт вашей проверки и публикации: {result.edit_url}'
        )
    except Exception as exc:
        logger.exception("WordPress draft preparation failed for job %s", job_id)
        job.status = UploadJobStatus.FAILED
        job.message = f"Не удалось подготовить черновик: {exc}"


# --- php_fixer passthroughs (thin — the actual logic lives in php_fixer.py,
# this only exists so handlers.py has one module to import dispatcher-facing
# functions from, matching every other module's handlers.py/service_layer.py
# split in this project) ---


def generate_php_fix(problem_description: str, context_snippet: str | None = None) -> dict[str, object]:
    fix = php_fixer.generate_fix(problem_description, context_snippet)
    return {"filename": fix.filename, "problem_description": fix.problem_description}


def list_php_fixes() -> list[dict[str, object]]:
    return php_fixer.list_fixes()


def get_php_fix_code(filename: str) -> str:
    return php_fixer.get_fix_code(filename)


def mark_php_fix_reviewed(filename: str) -> None:
    php_fixer.mark_reviewed(filename)


def discard_php_fix(filename: str) -> None:
    php_fixer.discard_fix(filename)
