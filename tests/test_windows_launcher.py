from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from windows_launcher import installed_user_data_root


def test_windows_launcher_derives_user_data_from_install_path():
    install = Path("/Users/Daniel/AppData/Local/Programs/RosterMate")

    assert installed_user_data_root(install) == Path("/Users/Daniel/AppData/Local/RosterMate")
