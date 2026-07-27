from __future__ import annotations

from types import SimpleNamespace

import credentials


def test_macos_password_uses_keychain_command(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(credentials.sys, "platform", "darwin")
    monkeypatch.setattr(credentials.os, "name", "posix")
    monkeypatch.setattr(credentials.subprocess, "run", fake_run)

    credentials.set_password("12345", "secret")

    command, kwargs = calls[0]
    assert command[:4] == ["security", "add-generic-password", "-U", "-s"]
    assert "RosterMate SelfService" in command
    assert kwargs["check"] is True


def test_windows_password_uses_system_keyring(monkeypatch):
    calls = []
    backend = SimpleNamespace(set_password=lambda service, account, password: calls.append((service, account, password)))
    monkeypatch.setattr(credentials.sys, "platform", "win32")
    monkeypatch.setattr(credentials, "_keyring", lambda: backend)

    credentials.set_password("12345", "secret")

    assert calls == [("RosterMate SelfService", "12345", "secret")]
