from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SelfServiceSessionStore:
    driver_id: str
    storage_state_path: Path
    user_data_dir: Path

    @classmethod
    def from_paths(cls, driver_id: str, paths: dict[str, Path]) -> "SelfServiceSessionStore":
        return cls(
            driver_id=driver_id,
            storage_state_path=paths["selfservice_storage_state_path"],
            user_data_dir=paths["selfservice_user_data_dir"],
        )

    def has_saved_session(self) -> bool:
        return self.storage_state_path.exists() and self.storage_state_path.stat().st_size > 0

    @property
    def session_storage_state_path(self) -> Path:
        return self.storage_state_path.with_name("selfservice_session_storage.json")

    def clear(self) -> None:
        if self.storage_state_path.exists():
            self.storage_state_path.unlink()
        if self.session_storage_state_path.exists():
            self.session_storage_state_path.unlink()
        if self.user_data_dir.exists():
            shutil.rmtree(self.user_data_dir, ignore_errors=True)
