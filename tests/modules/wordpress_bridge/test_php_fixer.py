from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from modules.wordpress_bridge import php_fixer


@pytest.fixture(autouse=True)
def _isolated_fixes_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fixes_dir = tmp_path / "_generated_fixes"
    fixes_dir.mkdir()
    monkeypatch.setattr(php_fixer, "FIXES_DIR", fixes_dir)
    return fixes_dir


def _fake_completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout, stderr="")


def test_generate_fix_extracts_code_and_saves_to_disk(_isolated_fixes_dir: Path) -> None:
    fake_response = (
        '{"result": "\\u041e\\u0442\\u0432\\u0435\\u0442:\\n```php\\n<?php\\n'
        "add_filter('foo', function() { return 1; });\\n```\"}"
    )
    completed = _fake_completed(fake_response)

    with patch.object(php_fixer, "invoke_claude_code", return_value=completed) as mock_invoke:
        fix = php_fixer.generate_fix("featured image не сохраняется", "some theme context")

    assert "add_filter" in fix.php_code
    assert fix.php_code.startswith("<?php")
    saved_path = _isolated_fixes_dir / fix.filename
    assert saved_path.is_file()
    assert saved_path.read_text(encoding="utf-8") == fix.php_code
    assert (_isolated_fixes_dir / f"{fix.filename}.meta.json").is_file()

    # never grants file-write/edit tools or Bash — this is a WordPress
    # install outside the repo, there's nothing safe to scope writes to.
    _, kwargs = mock_invoke.call_args
    assert kwargs["allowed_tools"] is None
    assert kwargs["permission_mode"] is None
    assert "Write" in kwargs["disallowed_tools"]


def test_generate_fix_raises_on_cli_failure(_isolated_fixes_dir: Path) -> None:
    completed = _fake_completed("boom", returncode=1)
    completed = subprocess.CompletedProcess(args=["claude"], returncode=1, stdout="", stderr="boom")
    with patch.object(php_fixer, "invoke_claude_code", return_value=completed):
        with pytest.raises(RuntimeError):
            php_fixer.generate_fix("some problem")


def test_list_get_review_discard_roundtrip(_isolated_fixes_dir: Path) -> None:
    completed = _fake_completed('{"result": "```php\\n<?php echo 1;\\n```"}')
    with patch.object(php_fixer, "invoke_claude_code", return_value=completed):
        fix = php_fixer.generate_fix("problem")

    listed = php_fixer.list_fixes()
    assert len(listed) == 1
    assert listed[0]["filename"] == fix.filename
    assert listed[0]["reviewed"] is False

    code = php_fixer.get_fix_code(fix.filename)
    assert "echo 1" in code

    php_fixer.mark_reviewed(fix.filename)
    assert php_fixer.list_fixes()[0]["reviewed"] is True

    php_fixer.discard_fix(fix.filename)
    assert php_fixer.list_fixes() == []


def test_get_fix_code_rejects_path_traversal(_isolated_fixes_dir: Path) -> None:
    with pytest.raises(ValueError):
        php_fixer.get_fix_code("../../etc/passwd")
