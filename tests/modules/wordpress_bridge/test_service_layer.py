from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from modules.wordpress_bridge import service_layer
from modules.wordpress_bridge.domain import DraftContent, DraftResult, UploadJobStatus


@pytest.fixture(autouse=True)
def _clear_jobs() -> None:
    service_layer._jobs.clear()
    yield
    service_layer._jobs.clear()


def test_create_and_get_job() -> None:
    job = service_layer.create_job("https://example.com")
    assert job.status == UploadJobStatus.RECEIVED
    assert service_layer.get_job(job.job_id) is job
    assert service_layer.get_job("unknown") is None


@pytest.mark.asyncio
async def test_run_upload_job_success_sets_draft_ready() -> None:
    job = service_layer.create_job("https://example.com")
    draft = DraftContent(title="Заголовок", html_body="<p>тело</p>")

    with (
        patch.object(service_layer.content_processor, "build_draft_content", return_value=draft),
        patch.object(
            service_layer.wp_draft_publisher,
            "publish_draft",
            new=AsyncMock(return_value=DraftResult(edit_url="https://example.com/wp-admin/post.php?post=1", title="Заголовок")),
        ),
    ):
        await service_layer.run_upload_job(job.job_id, ["/tmp/fake.docx"])

    assert job.status == UploadJobStatus.DRAFT_READY
    assert job.edit_url == "https://example.com/wp-admin/post.php?post=1"
    assert "Заголовок" in job.message


@pytest.mark.asyncio
async def test_run_upload_job_failure_sets_failed_status() -> None:
    job = service_layer.create_job("https://example.com")

    with patch.object(service_layer.content_processor, "build_draft_content", side_effect=RuntimeError("boom")):
        await service_layer.run_upload_job(job.job_id, ["/tmp/fake.docx"])

    assert job.status == UploadJobStatus.FAILED
    assert "boom" in job.message


@pytest.mark.asyncio
async def test_run_upload_job_unknown_job_id_does_not_raise() -> None:
    await service_layer.run_upload_job("does-not-exist", [])
