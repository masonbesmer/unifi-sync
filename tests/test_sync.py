import os
import sys
import pytest
import httpx
import respx
from unittest.mock import AsyncMock, MagicMock, patch


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
        "https://api.ui.com/v1/connector/consoles/host-abc/proxy/network/api/self/sites"
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
        "https://api.ui.com/v1/connector/consoles/host-abc/proxy/network/api/self/sites"
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


# --- Pure helper tests ---

def test_is_tagged_matches_name():
    from sync import is_tagged
    assert is_tagged({"name": "unifi-sync http", "comment": ""}, "unifi-sync") is True


def test_is_tagged_matches_comment():
    from sync import is_tagged
    assert is_tagged({"name": "my-rule", "comment": "unifi-sync"}, "unifi-sync") is True


def test_is_tagged_no_match():
    from sync import is_tagged
    assert is_tagged({"name": "manual-rule", "comment": ""}, "unifi-sync") is False


def test_make_wan_rule_overrides_fwd_ip():
    from sync import make_wan_rule
    local = {
        "name": "unifi-sync ssh", "proto": "tcp",
        "dst_port": "22", "fwd_port": "22",
        "fwd_ip": "10.0.0.99", "enabled": True,
    }
    result = make_wan_rule(local, "192.168.1.50")
    assert result["fwd_ip"] == "192.168.1.50"
    assert result["name"] == "unifi-sync ssh"
    assert result["proto"] == "tcp"
    assert result["dst_port"] == "22"
    assert result["fwd_port"] == "22"
    assert result["enabled"] is True
    assert "_id" not in result


def test_rules_differ_detects_port_change():
    from sync import rules_differ
    local = {"proto": "tcp", "dst_port": "8080", "fwd_port": "80", "enabled": True}
    wan = {"proto": "tcp", "dst_port": "9090", "fwd_port": "80", "enabled": True}
    assert rules_differ(local, wan) is True


def test_rules_differ_detects_proto_change():
    from sync import rules_differ
    local = {"proto": "tcp", "dst_port": "80", "fwd_port": "80", "enabled": True}
    wan = {"proto": "udp", "dst_port": "80", "fwd_port": "80", "enabled": True}
    assert rules_differ(local, wan) is True


def test_rules_differ_returns_false_when_same():
    from sync import rules_differ
    rule = {"proto": "tcp", "dst_port": "80", "fwd_port": "80", "enabled": True}
    assert rules_differ(rule, rule) is False


# --- Sync orchestration tests ---

async def test_sync_creates_missing_rule():
    from sync import sync, Config
    config = Config(
        wan_api_key="w", local_api_key="l", local_router_lan_adr="10.0.0.1",
        dry_run=False, sync_schedule=None, sync_tag="unifi-sync",
        wan_host_id=None, local_host_id=None,
    )
    local_rules = [
        {"name": "unifi-sync http", "proto": "tcp", "dst_port": "80",
         "fwd_port": "80", "fwd_ip": "192.168.0.10", "enabled": True}
    ]
    local_client = MagicMock()
    local_client.list_port_forwards = AsyncMock(return_value=local_rules)
    wan_client = MagicMock()
    wan_client.list_port_forwards = AsyncMock(return_value=[])
    wan_client.create_port_forward = AsyncMock(return_value={})
    await sync(local_client, wan_client, config)
    wan_client.create_port_forward.assert_awaited_once()
    call_arg = wan_client.create_port_forward.call_args[0][0]
    assert call_arg["fwd_ip"] == "10.0.0.1"


async def test_sync_deletes_removed_rule():
    from sync import sync, Config
    config = Config(
        wan_api_key="w", local_api_key="l", local_router_lan_adr="10.0.0.1",
        dry_run=False, sync_schedule=None, sync_tag="unifi-sync",
        wan_host_id=None, local_host_id=None,
    )
    wan_rules = [
        {"_id": "rule-1", "name": "unifi-sync http", "proto": "tcp",
         "dst_port": "80", "fwd_port": "80", "fwd_ip": "10.0.0.1", "enabled": True}
    ]
    local_client = MagicMock()
    local_client.list_port_forwards = AsyncMock(return_value=[])
    wan_client = MagicMock()
    wan_client.list_port_forwards = AsyncMock(return_value=wan_rules)
    wan_client.delete_port_forward = AsyncMock(return_value=None)
    await sync(local_client, wan_client, config)
    wan_client.delete_port_forward.assert_awaited_once_with("rule-1")


async def test_sync_updates_changed_rule():
    from sync import sync, Config
    config = Config(
        wan_api_key="w", local_api_key="l", local_router_lan_adr="10.0.0.1",
        dry_run=False, sync_schedule=None, sync_tag="unifi-sync",
        wan_host_id=None, local_host_id=None,
    )
    local_rules = [
        {"name": "unifi-sync http", "proto": "tcp", "dst_port": "8080",
         "fwd_port": "80", "fwd_ip": "192.168.0.10", "enabled": True}
    ]
    wan_rules = [
        {"_id": "rule-1", "name": "unifi-sync http", "proto": "tcp",
         "dst_port": "80", "fwd_port": "80", "fwd_ip": "10.0.0.1", "enabled": True}
    ]
    local_client = MagicMock()
    local_client.list_port_forwards = AsyncMock(return_value=local_rules)
    wan_client = MagicMock()
    wan_client.list_port_forwards = AsyncMock(return_value=wan_rules)
    wan_client.update_port_forward = AsyncMock(return_value={})
    await sync(local_client, wan_client, config)
    wan_client.update_port_forward.assert_awaited_once_with("rule-1", {
        "name": "unifi-sync http", "proto": "tcp", "dst_port": "8080",
        "fwd_port": "80", "fwd_ip": "10.0.0.1", "enabled": True,
    })


async def test_sync_noop_when_already_in_sync():
    from sync import sync, Config
    config = Config(
        wan_api_key="w", local_api_key="l", local_router_lan_adr="10.0.0.1",
        dry_run=False, sync_schedule=None, sync_tag="unifi-sync",
        wan_host_id=None, local_host_id=None,
    )
    rule = {
        "_id": "r1", "name": "unifi-sync http", "proto": "tcp",
        "dst_port": "80", "fwd_port": "80", "fwd_ip": "10.0.0.1", "enabled": True,
    }
    local_client = MagicMock()
    local_client.list_port_forwards = AsyncMock(return_value=[rule])
    wan_client = MagicMock()
    wan_client.list_port_forwards = AsyncMock(return_value=[rule])
    wan_client.create_port_forward = AsyncMock()
    wan_client.update_port_forward = AsyncMock()
    wan_client.delete_port_forward = AsyncMock()
    await sync(local_client, wan_client, config)
    wan_client.create_port_forward.assert_not_awaited()
    wan_client.update_port_forward.assert_not_awaited()
    wan_client.delete_port_forward.assert_not_awaited()


async def test_sync_dry_run_skips_all_writes():
    from sync import sync, Config
    config = Config(
        wan_api_key="w", local_api_key="l", local_router_lan_adr="10.0.0.1",
        dry_run=True, sync_schedule=None, sync_tag="unifi-sync",
        wan_host_id=None, local_host_id=None,
    )
    local_rules = [
        {"name": "unifi-sync http", "proto": "tcp", "dst_port": "80",
         "fwd_port": "80", "fwd_ip": "192.168.0.10", "enabled": True}
    ]
    local_client = MagicMock()
    local_client.list_port_forwards = AsyncMock(return_value=local_rules)
    wan_client = MagicMock()
    wan_client.list_port_forwards = AsyncMock(return_value=[])
    wan_client.create_port_forward = AsyncMock()
    await sync(local_client, wan_client, config)
    wan_client.create_port_forward.assert_not_awaited()


async def test_sync_ignores_untagged_rules():
    from sync import sync, Config
    config = Config(
        wan_api_key="w", local_api_key="l", local_router_lan_adr="10.0.0.1",
        dry_run=False, sync_schedule=None, sync_tag="unifi-sync",
        wan_host_id=None, local_host_id=None,
    )
    local_rules = [
        {"name": "manual-rule", "proto": "tcp", "dst_port": "443",
         "fwd_port": "443", "fwd_ip": "192.168.0.5", "enabled": True}
    ]
    local_client = MagicMock()
    local_client.list_port_forwards = AsyncMock(return_value=local_rules)
    wan_client = MagicMock()
    wan_client.list_port_forwards = AsyncMock(return_value=[])
    wan_client.create_port_forward = AsyncMock()
    await sync(local_client, wan_client, config)
    wan_client.create_port_forward.assert_not_awaited()


async def test_sync_continues_after_single_rule_failure():
    from sync import sync, Config
    config = Config(
        wan_api_key="w", local_api_key="l", local_router_lan_adr="10.0.0.1",
        dry_run=False, sync_schedule=None, sync_tag="unifi-sync",
        wan_host_id=None, local_host_id=None,
    )
    local_rules = [
        {"name": "unifi-sync rule-a", "proto": "tcp", "dst_port": "80",
         "fwd_port": "80", "fwd_ip": "x", "enabled": True},
        {"name": "unifi-sync rule-b", "proto": "tcp", "dst_port": "443",
         "fwd_port": "443", "fwd_ip": "x", "enabled": True},
    ]
    local_client = MagicMock()
    local_client.list_port_forwards = AsyncMock(return_value=local_rules)
    wan_client = MagicMock()
    wan_client.list_port_forwards = AsyncMock(return_value=[])
    call_count = 0

    async def create_side_effect(rule):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("API error on first rule")
        return {}

    wan_client.create_port_forward = create_side_effect
    await sync(local_client, wan_client, config)
    assert call_count == 2


# --- main() entrypoint tests ---

async def test_main_run_once_calls_close(monkeypatch):
    """main() calls close() on both clients even in run-once mode."""
    monkeypatch.setenv("WAN_ROUTER_API_KEY", "w")
    monkeypatch.setenv("LOCAL_ROUTER_API_KEY", "l")
    monkeypatch.setenv("LOCAL_ROUTER_LAN_ADR", "10.0.0.1")
    monkeypatch.delenv("SYNC_SCHEDULE", raising=False)

    mock_local = MagicMock()
    mock_local.discover = AsyncMock()
    mock_local.list_port_forwards = AsyncMock(return_value=[])
    mock_local.close = AsyncMock()

    mock_wan = MagicMock()
    mock_wan.discover = AsyncMock()
    mock_wan.list_port_forwards = AsyncMock(return_value=[])
    mock_wan.close = AsyncMock()

    with patch("sync.UnifiClient", side_effect=[mock_local, mock_wan]):
        from sync import main
        await main()

    mock_local.close.assert_awaited_once()
    mock_wan.close.assert_awaited_once()


async def test_main_close_called_even_on_discover_error(monkeypatch):
    """main() finally block closes clients even when discover() raises."""
    monkeypatch.setenv("WAN_ROUTER_API_KEY", "w")
    monkeypatch.setenv("LOCAL_ROUTER_API_KEY", "l")
    monkeypatch.setenv("LOCAL_ROUTER_LAN_ADR", "10.0.0.1")
    monkeypatch.delenv("SYNC_SCHEDULE", raising=False)

    mock_local = MagicMock()
    mock_local.discover = AsyncMock(side_effect=RuntimeError("network down"))
    mock_local.close = AsyncMock()

    mock_wan = MagicMock()
    mock_wan.discover = AsyncMock()
    mock_wan.close = AsyncMock()

    with patch("sync.UnifiClient", side_effect=[mock_local, mock_wan]):
        from sync import main
        with pytest.raises(RuntimeError):
            await main()

    mock_local.close.assert_awaited_once()
    mock_wan.close.assert_awaited_once()


async def test_main_scheduler_used_when_sync_schedule_set(monkeypatch):
    """main() creates AsyncIOScheduler when SYNC_SCHEDULE is set."""
    monkeypatch.setenv("WAN_ROUTER_API_KEY", "w")
    monkeypatch.setenv("LOCAL_ROUTER_API_KEY", "l")
    monkeypatch.setenv("LOCAL_ROUTER_LAN_ADR", "10.0.0.1")
    monkeypatch.setenv("SYNC_SCHEDULE", "*/5 * * * *")

    mock_local = MagicMock()
    mock_local.discover = AsyncMock()
    mock_local.list_port_forwards = AsyncMock(return_value=[])
    mock_local.close = AsyncMock()

    mock_wan = MagicMock()
    mock_wan.discover = AsyncMock()
    mock_wan.list_port_forwards = AsyncMock(return_value=[])
    mock_wan.close = AsyncMock()

    mock_scheduler = MagicMock()
    mock_scheduler.add_job = MagicMock()
    mock_scheduler.start = MagicMock()

    # asyncio.Event().wait() would block forever; patch it to return immediately
    mock_event = MagicMock()
    mock_event.wait = AsyncMock(return_value=None)

    with patch("sync.UnifiClient", side_effect=[mock_local, mock_wan]), \
         patch("sync.AsyncIOScheduler", return_value=mock_scheduler), \
         patch("sync.asyncio.Event", return_value=mock_event):
        from sync import main
        await main()

    mock_scheduler.add_job.assert_called_once()
    mock_scheduler.start.assert_called_once()
    # Verify add_job was called with a callable (run_sync) and a CronTrigger positional arg
    call_args = mock_scheduler.add_job.call_args
    assert call_args is not None
    assert len(call_args[0]) == 2  # (run_sync, trigger) as positional args
    mock_local.close.assert_awaited_once()
    mock_wan.close.assert_awaited_once()


async def test_sync_dry_run_skips_delete():
    from sync import sync, Config
    config = Config(
        wan_api_key="w", local_api_key="l", local_router_lan_adr="10.0.0.1",
        dry_run=True, sync_schedule=None, sync_tag="unifi-sync",
        wan_host_id=None, local_host_id=None,
    )
    wan_rules = [
        {"_id": "rule-1", "name": "unifi-sync http", "proto": "tcp",
         "dst_port": "80", "fwd_port": "80", "fwd_ip": "10.0.0.1", "enabled": True}
    ]
    local_client = MagicMock()
    local_client.list_port_forwards = AsyncMock(return_value=[])
    wan_client = MagicMock()
    wan_client.list_port_forwards = AsyncMock(return_value=wan_rules)
    wan_client.delete_port_forward = AsyncMock()
    await sync(local_client, wan_client, config)
    wan_client.delete_port_forward.assert_not_awaited()


async def test_sync_dry_run_skips_update():
    from sync import sync, Config
    config = Config(
        wan_api_key="w", local_api_key="l", local_router_lan_adr="10.0.0.1",
        dry_run=True, sync_schedule=None, sync_tag="unifi-sync",
        wan_host_id=None, local_host_id=None,
    )
    local_rules = [
        {"name": "unifi-sync http", "proto": "tcp", "dst_port": "8080",
         "fwd_port": "80", "fwd_ip": "192.168.0.10", "enabled": True}
    ]
    wan_rules = [
        {"_id": "rule-1", "name": "unifi-sync http", "proto": "tcp",
         "dst_port": "80", "fwd_port": "80", "fwd_ip": "10.0.0.1", "enabled": True}
    ]
    local_client = MagicMock()
    local_client.list_port_forwards = AsyncMock(return_value=local_rules)
    wan_client = MagicMock()
    wan_client.list_port_forwards = AsyncMock(return_value=wan_rules)
    wan_client.update_port_forward = AsyncMock()
    await sync(local_client, wan_client, config)
    wan_client.update_port_forward.assert_not_awaited()


@respx.mock
async def test_retry_on_network_error():
    from sync import UnifiClient
    client = UnifiClient("test-key", "TEST")
    call_count = 0
    def raise_network_error(request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.NetworkError("connection refused")
        return httpx.Response(200, json={"data": [{"id": "host-abc"}]})
    respx.get("https://api.ui.com/v1/hosts").mock(side_effect=raise_network_error)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        data = await client._request_with_retry("GET", "/v1/hosts")
    assert data["data"][0]["id"] == "host-abc"
    await client.close()


def test_is_tagged_missing_comment_key():
    from sync import is_tagged
    assert is_tagged({"name": "unifi-sync rule"}, "unifi-sync") is True
    assert is_tagged({"name": "manual"}, "unifi-sync") is False


async def test_main_run_sync_swallows_exceptions(monkeypatch):
    """run_sync() catches sync() exceptions without propagating."""
    monkeypatch.setenv("WAN_ROUTER_API_KEY", "w")
    monkeypatch.setenv("LOCAL_ROUTER_API_KEY", "l")
    monkeypatch.setenv("LOCAL_ROUTER_LAN_ADR", "10.0.0.1")
    monkeypatch.delenv("SYNC_SCHEDULE", raising=False)

    mock_local = MagicMock()
    mock_local.discover = AsyncMock()
    mock_local.list_port_forwards = AsyncMock(side_effect=RuntimeError("sync failed"))
    mock_local.close = AsyncMock()

    mock_wan = MagicMock()
    mock_wan.discover = AsyncMock()
    mock_wan.list_port_forwards = AsyncMock(return_value=[])
    mock_wan.close = AsyncMock()

    with patch("sync.UnifiClient", side_effect=[mock_local, mock_wan]):
        from sync import main
        # Should complete without raising (run_sync swallows the exception)
        await main()

    mock_local.close.assert_awaited_once()
    mock_wan.close.assert_awaited_once()
