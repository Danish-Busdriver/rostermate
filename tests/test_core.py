import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import compare_plans, create_backup, load_history, save_history


def test_compare_plans_detects_added_removed_and_changed_items(tmp_path):
    old_plan = [
        {"id": "shift-1", "title": "Morgenvagt", "date": "2026-07-08"},
        {"id": "shift-2", "title": "Aftenvagt", "date": "2026-07-09"},
    ]
    new_plan = [
        {"id": "shift-1", "title": "Morgenvagt ændret", "date": "2026-07-08"},
        {"id": "shift-3", "title": "Natvagt", "date": "2026-07-10"},
    ]

    changes = compare_plans(old_plan, new_plan)

    assert any(change["type"] == "removed" for change in changes)
    assert any(change["type"] == "added" for change in changes)
    assert any(change["type"] == "changed" for change in changes)


def test_backup_and_history_round_trip(tmp_path):
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    data_dir.mkdir(parents=True)
    backup_dir.mkdir(parents=True)

    history_path = data_dir / "history.json"
    history = [{"id": 1, "summary": "Initial import"}]
    save_history(history, history_path)

    backup_path = create_backup(history_path, backup_dir)

    assert backup_path.exists()
    assert load_history(history_path)[0]["summary"] == "Initial import"
