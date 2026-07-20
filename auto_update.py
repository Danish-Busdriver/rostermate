from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class UpdateResult:
    status: str
    message: str
    updated: bool = False


def _run(runner: Runner, command: list[str], project_dir: Path) -> subprocess.CompletedProcess[str]:
    return runner(command, cwd=project_dir, capture_output=True, text=True, check=False)


def check_for_updates(project_dir: Path, runner: Runner = subprocess.run) -> UpdateResult:
    """Fast-forward the checked-out branch from its configured upstream."""
    if os.environ.get("ROSTERMATE_SKIP_UPDATE", "").lower() in {"1", "true", "yes"}:
        return UpdateResult("skipped", "Automatisk opdatering er slået fra.")
    if not (project_dir / ".git").exists():
        return UpdateResult("skipped", "Ingen Git-installation fundet; fortsætter uden opdatering.")

    dirty = _run(runner, ["git", "status", "--porcelain", "--untracked-files=no"], project_dir)
    if dirty.returncode != 0:
        return UpdateResult("error", "Kunne ikke kontrollere lokale ændringer; fortsætter uden opdatering.")
    if dirty.stdout.strip():
        return UpdateResult("skipped", "Lokale kodeændringer fundet; automatisk opdatering springes over.")

    upstream = _run(
        runner,
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        project_dir,
    )
    if upstream.returncode != 0 or not upstream.stdout.strip():
        return UpdateResult("skipped", "Branchen har ingen GitHub tracking-branch.")
    upstream_name = upstream.stdout.strip()

    fetched = _run(runner, ["git", "fetch", "--quiet"], project_dir)
    if fetched.returncode != 0:
        return UpdateResult("offline", "GitHub kunne ikke nås; starter den installerede version.")

    local_head = _run(runner, ["git", "rev-parse", "HEAD"], project_dir)
    remote_head = _run(runner, ["git", "rev-parse", upstream_name], project_dir)
    if local_head.returncode != 0 or remote_head.returncode != 0:
        return UpdateResult("error", "Kunne ikke sammenligne lokale og eksterne versioner.")
    if local_head.stdout.strip() == remote_head.stdout.strip():
        return UpdateResult("current", "RosterMate er opdateret.")

    ancestor = _run(runner, ["git", "merge-base", "--is-ancestor", "HEAD", upstream_name], project_dir)
    if ancestor.returncode != 0:
        return UpdateResult("skipped", "Lokal og ekstern branch er forskellige; opdaterer ikke automatisk.")

    requirements_path = project_dir / "requirements.txt"
    requirements_before = requirements_path.read_bytes() if requirements_path.exists() else b""
    merged = _run(runner, ["git", "merge", "--ff-only", upstream_name], project_dir)
    if merged.returncode != 0:
        return UpdateResult("error", "Git-opdateringen kunne ikke anvendes; starter den installerede version.")

    requirements_after = requirements_path.read_bytes() if requirements_path.exists() else b""
    if requirements_after != requirements_before:
        dependencies = _run(
            runner,
            [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)],
            project_dir,
        )
        if dependencies.returncode != 0:
            return UpdateResult(
                "updated-with-warning",
                "Koden blev opdateret, men nye afhængigheder kunne ikke installeres.",
                updated=True,
            )

    return UpdateResult("updated", "RosterMate blev automatisk opdateret fra GitHub.", updated=True)


def main() -> int:
    result = check_for_updates(Path(__file__).resolve().parent)
    print(f"[RosterMate update] {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
