from __future__ import annotations

import json
from pathlib import Path

import port_config


def test_configured_port_defaults_to_8080(tmp_path, monkeypatch):
    monkeypatch.delenv("ROSTERMATE_PORT", raising=False)

    assert port_config.configured_port(root=tmp_path) == 8080


def test_port_can_be_saved_for_the_installation(tmp_path, monkeypatch):
    monkeypatch.delenv("ROSTERMATE_PORT", raising=False)

    port_config.save_port(8094, root=tmp_path)

    assert port_config.configured_port(root=tmp_path) == 8094
    assert json.loads((tmp_path / "data" / "app-config.json").read_text(encoding="utf-8")) == {"port": 8094}


def test_invalid_ports_are_rejected():
    assert port_config.valid_port("1023") is None
    assert port_config.valid_port("65536") is None
    assert port_config.valid_port("not-a-port") is None
    assert port_config.valid_port("8088") == 8088


def test_ensure_port_falls_back_when_configured_port_is_busy(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTERMATE_HOME", str(tmp_path))
    monkeypatch.delenv("ROSTERMATE_PORT", raising=False)
    monkeypatch.setattr(port_config, "port_is_available", lambda port: port == 8083)

    selected = port_config.ensure_available_port()

    assert selected == 8083
    assert port_config.configured_port() == 8083
