from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class UploadJobStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    DRAFT_READY = "draft_ready"
    FAILED = "failed"


@dataclass
class DraftContent:
    """The result of turning one or more uploaded files into WordPress
    draft material — everything wp_draft_publisher.py needs and nothing it
    has to figure out itself."""

    title: str
    html_body: str
    image_paths: list[str] = field(default_factory=list)
    featured_image_path: str | None = None


@dataclass
class DraftResult:
    edit_url: str
    title: str


@dataclass
class UploadJob:
    job_id: str
    site_url: str
    status: UploadJobStatus = UploadJobStatus.RECEIVED
    message: str = ""
    edit_url: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GeneratedFix:
    """A php_fixer.py output — always saved to disk under
    _generated_fixes/, never applied to a live site by this code. `status`
    is purely local bookkeeping (reviewed vs. discarded); the fix itself is
    already "applied" in the only sense this module ever performs that
    word — saved locally for the user to copy in by hand."""

    slug: str
    problem_description: str
    php_code: str
    created_at: datetime
    reviewed: bool = False

    @property
    def filename(self) -> str:
        return f"{self.created_at.strftime('%Y-%m-%d')}_{self.slug}.php"
