from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_update import check_for_updates


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str]]) -> None:
        self.responses = responses
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        key = tuple(command)
        self.commands.append(key)
        returncode, stdout = self.responses.get(key, (0, ""))
        return subprocess.CompletedProcess(command, returncode, stdout, "")


def git_project(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "requirements.txt").write_text("Flask>=3\n", encoding="utf-8")
    return tmp_path


def test_update_is_skipped_when_tracked_files_are_modified(tmp_path):
    project_dir = git_project(tmp_path)
    runner = FakeRunner({("git", "status", "--porcelain", "--untracked-files=no"): (0, " M app.py\n")})

    result = check_for_updates(project_dir, runner=runner)

    assert result.status == "skipped"
    assert ("git", "fetch", "--quiet") not in runner.commands


def test_update_starts_installed_version_when_github_is_offline(tmp_path):
    project_dir = git_project(tmp_path)
    runner = FakeRunner(
        {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): (0, "origin/main\n"),
            ("git", "fetch", "--quiet"): (1, ""),
        }
    )

    result = check_for_updates(project_dir, runner=runner)

    assert result.status == "offline"
    assert result.updated is False


def test_update_fast_forwards_when_remote_is_ahead(tmp_path):
    project_dir = git_project(tmp_path)
    runner = FakeRunner(
        {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): (0, "origin/main\n"),
            ("git", "rev-parse", "HEAD"): (0, "local\n"),
            ("git", "rev-parse", "origin/main"): (0, "remote\n"),
        }
    )

    result = check_for_updates(project_dir, runner=runner)

    assert result.status == "updated"
    assert result.updated is True
    assert ("git", "merge", "--ff-only", "origin/main") in runner.commands
