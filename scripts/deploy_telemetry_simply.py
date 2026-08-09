from __future__ import annotations

import ftplib
import json
import ssl
from pathlib import Path

import certifi


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (".htaccess", "bootstrap.php", "heartbeat.php", "stats.php", "cleanup.php")


def ensure_directory(ftp: ftplib.FTP_TLS, path: str) -> None:
    current = ""
    for part in path.strip("/").split("/"):
        current += "/" + part
        try:
            ftp.mkd(current)
        except ftplib.error_perm as exc:
            if not str(exc).startswith("550"):
                raise


def upload_file(ftp: ftplib.FTP_TLS, local_path: Path, remote_path: str) -> None:
    with local_path.open("rb") as handle:
        ftp.storbinary(f"STOR {remote_path}", handle)


def main() -> None:
    credentials = json.loads((ROOT / "simply-ftp.json").read_text(encoding="utf-8"))
    if credentials.get("password") == "INDSAET_FTP_ADGANGSKODE_HER":
        raise SystemExit("FTP-adgangskoden mangler i simply-ftp.json")
    server_dir = ROOT / "telemetry-server"
    context = ssl.create_default_context(cafile=certifi.where())
    with ftplib.FTP_TLS(context=context) as ftp:
        ftp.connect(str(credentials["host"]), int(credentials.get("port", 21)), timeout=20)
        ftp.login(str(credentials["username"]), str(credentials["password"]))
        ftp.prot_p()
        ftp.set_pasv(True)
        ensure_directory(ftp, "/rostermate/telemetry")
        for filename in PUBLIC_FILES:
            upload_file(ftp, server_dir / filename, f"/rostermate/telemetry/{filename}")
        upload_file(ftp, server_dir / "config.php", "/rostermate-telemetry-config.php")
    print("Telemetrifiler uploadet via FTPS.")


if __name__ == "__main__":
    main()
