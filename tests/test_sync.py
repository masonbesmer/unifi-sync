import os
import sys
import pytest


def test_load_config_exits_when_all_required_missing(monkeypatch):
    for key in ("WAN_ROUTER_API_KEY", "LOCAL_ROUTER_API_KEY", "LOCAL_ROUTER_LAN_ADR"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit) as exc_info:
        from sync import load_config
        load_config()
    assert exc_info.value.code == 1


def test_load_config_exits_when_one_required_missing(monkeypatch):
    monkeypatch.setenv("WAN_ROUTER_API_KEY", "wan-key")
    monkeypatch.setenv("LOCAL_ROUTER_API_KEY", "local-key")
    monkeypatch.delenv("LOCAL_ROUTER_LAN_ADR", raising=False)
    with pytest.raises(SystemExit):
        from sync import load_config
        load_config()


def test_load_config_applies_defaults(monkeypatch):
    monkeypatch.setenv("WAN_ROUTER_API_KEY", "wan-key")
    monkeypatch.setenv("LOCAL_ROUTER_API_KEY", "local-key")
    monkeypatch.setenv("LOCAL_ROUTER_LAN_ADR", "10.0.0.1")
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("SYNC_SCHEDULE", raising=False)
    monkeypatch.delenv("SYNC_TAG", raising=False)
    from sync import load_config
    config = load_config()
    assert config.wan_api_key == "wan-key"
    assert config.local_api_key == "local-key"
    assert config.local_router_lan_adr == "10.0.0.1"
    assert config.dry_run is False
    assert config.sync_schedule is None
    assert config.sync_tag == "unifi-sync"


def test_load_config_reads_explicit_values(monkeypatch):
    monkeypatch.setenv("WAN_ROUTER_API_KEY", "w")
    monkeypatch.setenv("LOCAL_ROUTER_API_KEY", "l")
    monkeypatch.setenv("LOCAL_ROUTER_LAN_ADR", "192.168.1.1")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("SYNC_SCHEDULE", "*/5 * * * *")
    monkeypatch.setenv("SYNC_TAG", "my-tag")
    from sync import load_config
    config = load_config()
    assert config.dry_run is True
    assert config.sync_schedule == "*/5 * * * *"
    assert config.sync_tag == "my-tag"
