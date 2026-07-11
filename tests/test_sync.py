import os
import sys
import pytest
import httpx
import respx
from unittest.mock import AsyncMock, patch


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


@respx.mock
async def test_discover_sets_host_and_site():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    respx.get("https://api.ui.com/v1/hosts").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "host-abc"}]})
    )
    respx.get(
        "https://api.ui.com/v1/connector/consoles/host-abc/proxy/network/v1/sites"
    ).mock(return_value=httpx.Response(200, json={"data": [{"name": "default"}]}))
    await client.discover()
    assert client.host_id == "host-abc"
    assert client.site_id == "default"
    await client.close()


@respx.mock
async def test_discover_exits_on_empty_hosts():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    respx.get("https://api.ui.com/v1/hosts").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    with pytest.raises(SystemExit):
        await client.discover()
    await client.close()


@respx.mock
async def test_discover_exits_on_empty_sites():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    respx.get("https://api.ui.com/v1/hosts").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "host-abc"}]})
    )
    respx.get(
        "https://api.ui.com/v1/connector/consoles/host-abc/proxy/network/v1/sites"
    ).mock(return_value=httpx.Response(200, json={"data": []}))
    with pytest.raises(SystemExit):
        await client.discover()
    await client.close()


@respx.mock
async def test_list_port_forwards():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    client.host_id = "host-abc"
    client.site_id = "default"
    rules = [
        {
            "_id": "1", "name": "unifi-sync http", "proto": "tcp",
            "dst_port": "8080", "fwd_port": "80", "fwd_ip": "10.0.0.2", "enabled": True,
        }
    ]
    respx.get(
        "https://api.ui.com/v1/connector/consoles/host-abc/proxy/network/api/s/default/rest/portforward"
    ).mock(return_value=httpx.Response(200, json={"data": rules}))
    result = await client.list_port_forwards()
    assert result == rules
    await client.close()


@respx.mock
async def test_create_port_forward():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    client.host_id = "host-abc"
    client.site_id = "default"
    rule = {"name": "unifi-sync ssh", "proto": "tcp", "dst_port": "22", "fwd_port": "22", "fwd_ip": "10.0.0.5", "enabled": True}
    respx.post(
        "https://api.ui.com/v1/connector/consoles/host-abc/proxy/network/api/s/default/rest/portforward"
    ).mock(return_value=httpx.Response(200, json={"data": [rule]}))
    result = await client.create_port_forward(rule)
    assert result["data"][0]["name"] == "unifi-sync ssh"
    await client.close()


@respx.mock
async def test_update_port_forward():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    client.host_id = "host-abc"
    client.site_id = "default"
    rule = {"name": "unifi-sync ssh", "proto": "tcp", "dst_port": "2222", "fwd_port": "22", "fwd_ip": "10.0.0.5", "enabled": True}
    respx.put(
        "https://api.ui.com/v1/connector/consoles/host-abc/proxy/network/api/s/default/rest/portforward/rule-1"
    ).mock(return_value=httpx.Response(200, json={"data": [rule]}))
    result = await client.update_port_forward("rule-1", rule)
    assert result["data"][0]["dst_port"] == "2222"
    await client.close()


@respx.mock
async def test_delete_port_forward():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    client.host_id = "host-abc"
    client.site_id = "default"
    respx.delete(
        "https://api.ui.com/v1/connector/consoles/host-abc/proxy/network/api/s/default/rest/portforward/rule-1"
    ).mock(return_value=httpx.Response(200, json={"data": []}))
    await client.delete_port_forward("rule-1")
    await client.close()


@respx.mock
async def test_retry_succeeds_on_third_attempt():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    route = respx.get("https://api.ui.com/v1/hosts")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json={"data": [{"id": "host-abc"}]}),
    ]
    with patch("asyncio.sleep", new_callable=AsyncMock):
        data = await client._request_with_retry("GET", "/v1/hosts")
    assert data["data"][0]["id"] == "host-abc"
    await client.close()


@respx.mock
async def test_retry_raises_after_all_attempts_exhausted():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    respx.get("https://api.ui.com/v1/hosts").mock(
        return_value=httpx.Response(503)
    )
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(httpx.HTTPStatusError):
            await client._request_with_retry("GET", "/v1/hosts")
    await client.close()
