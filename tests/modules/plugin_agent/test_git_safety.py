from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from modules.plugin_agent import git_safety


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["git"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_is_git_repo_true_when_git_reports_inside_work_tree(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "_run_git", lambda *a, **k: _completed(0, "true\n"))

    assert git_safety.is_git_repo() is True


def test_is_git_repo_false_on_nonzero_exit(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "_run_git", lambda *a, **k: _completed(128, ""))

    assert git_safety.is_git_repo() is False


def test_ensure_git_repo_does_nothing_if_already_a_repo(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "is_git_repo", lambda: True)
    calls = MagicMock()
    monkeypatch.setattr(git_safety, "_run_git", calls)

    git_safety.ensure_git_repo()

    calls.assert_not_called()


def test_ensure_git_repo_initializes_and_commits_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "is_git_repo", lambda: False)
    calls: list[tuple] = []

    def fake_run_git(*args: str, check: bool = True):
        calls.append(args)
        return _completed(0)

    monkeypatch.setattr(git_safety, "_run_git", fake_run_git)

    git_safety.ensure_git_repo()

    assert ("init",) in calls
    assert any(a[0] == "commit" for a in calls)


def test_ensure_git_repo_raises_git_safety_error_when_init_fails(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "is_git_repo", lambda: False)

    def fake_run_git(*args: str, check: bool = True):
        if args[0] == "init":
            return _completed(1, "", "permission denied")
        return _completed(0)

    monkeypatch.setattr(git_safety, "_run_git", fake_run_git)

    with pytest.raises(git_safety.GitSafetyError, match="permission denied"):
        git_safety.ensure_git_repo()


def test_snapshot_commits_when_there_are_changes_and_returns_head(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "ensure_git_repo", lambda: None)
    calls: list[tuple] = []

    def fake_run_git(*args: str, check: bool = True):
        calls.append(args)
        if args[0] == "status":
            return _completed(0, "M some_file.py\n")
        if args[0] == "rev-parse":
            return _completed(0, "abc123\n")
        return _completed(0)

    monkeypatch.setattr(git_safety, "_run_git", fake_run_git)

    result = git_safety.snapshot("test label")

    assert result == "abc123"
    assert any(a[0] == "commit" for a in calls)


def test_snapshot_skips_commit_when_nothing_changed(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "ensure_git_repo", lambda: None)
    calls: list[tuple] = []

    def fake_run_git(*args: str, check: bool = True):
        calls.append(args)
        if args[0] == "status":
            return _completed(0, "")
        if args[0] == "rev-parse":
            return _completed(0, "deadbeef\n")
        return _completed(0)

    monkeypatch.setattr(git_safety, "_run_git", fake_run_git)

    result = git_safety.snapshot("test label")

    assert result == "deadbeef"
    assert not any(a[0] == "commit" for a in calls)


def test_snapshot_raises_when_head_cannot_be_resolved(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "ensure_git_repo", lambda: None)

    def fake_run_git(*args: str, check: bool = True):
        if args[0] == "status":
            return _completed(0, "")
        if args[0] == "rev-parse":
            return _completed(1, "", "no commits yet")
        return _completed(0)

    monkeypatch.setattr(git_safety, "_run_git", fake_run_git)

    with pytest.raises(git_safety.GitSafetyError, match="no commits yet"):
        git_safety.snapshot("test label")


def test_enforce_pending_only_keeps_pending_dir_files(monkeypatch) -> None:
    status_output = "A  modules/plugins/_pending/foo.py\n"
    monkeypatch.setattr(git_safety, "_run_git", lambda *a, **k: _completed(0, status_output))

    result = git_safety.enforce_pending_only()

    assert result == {"kept": ["modules/plugins/_pending/foo.py"], "rolled_back": []}


def test_enforce_pending_only_removes_untracked_files_outside_pending_dir(monkeypatch, tmp_path) -> None:
    target = tmp_path / "stray_file.py"
    target.write_text("x")
    status_output = "?? stray_file.py\n"

    monkeypatch.setattr(git_safety, "BASE_DIR", tmp_path)
    monkeypatch.setattr(git_safety, "_run_git", lambda *a, **k: _completed(0, status_output))

    result = git_safety.enforce_pending_only()

    assert result == {"kept": [], "rolled_back": ["stray_file.py"]}
    assert not target.exists()


def test_enforce_pending_only_checks_out_tracked_files_outside_pending_dir(monkeypatch) -> None:
    calls: list[tuple] = []
    status_output = " M some_tracked_file.py\n"

    def fake_run_git(*args: str, check: bool = True):
        calls.append(args)
        return _completed(0, status_output if args and args[0] == "status" else "")

    monkeypatch.setattr(git_safety, "_run_git", fake_run_git)

    result = git_safety.enforce_pending_only()

    assert result == {"kept": [], "rolled_back": ["some_tracked_file.py"]}
    assert ("checkout", "--", "some_tracked_file.py") in calls


def test_commit_enabled_plugin_noop_when_not_a_git_repo(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "is_git_repo", lambda: False)
    calls = MagicMock()
    monkeypatch.setattr(git_safety, "_run_git", calls)

    git_safety.commit_enabled_plugin(Path("/whatever/plugin.py"))

    calls.assert_not_called()


def test_commit_enabled_plugin_noop_when_path_outside_base_dir(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "is_git_repo", lambda: True)
    calls = MagicMock()
    monkeypatch.setattr(git_safety, "_run_git", calls)

    git_safety.commit_enabled_plugin(Path("/completely/unrelated/path/plugin.py"))

    calls.assert_not_called()


def test_commit_enabled_plugin_adds_and_commits_when_inside_base_dir(monkeypatch) -> None:
    monkeypatch.setattr(git_safety, "is_git_repo", lambda: True)
    calls: list[tuple] = []

    def fake_run_git(*args: str, check: bool = True):
        calls.append(args)
        return _completed(0)

    monkeypatch.setattr(git_safety, "_run_git", fake_run_git)

    plugin_path = git_safety.BASE_DIR / "modules" / "plugins" / "my_plugin.py"
    git_safety.commit_enabled_plugin(plugin_path)

    assert ("add", "modules/plugins/my_plugin.py") in calls
    assert any(a[0] == "commit" for a in calls)
