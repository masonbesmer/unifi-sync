# UniFi Port Forward Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python Docker container that syncs tagged port forwarding rules from a LOCAL UniFi router to a WAN UniFi router via the UniFi Cloud API at `api.ui.com`.

**Architecture:** Single `sync.py` with a `UnifiClient` class (wraps `httpx.AsyncClient`), pure helper functions for sync logic, and an `asyncio` main entrypoint. APScheduler drives cron scheduling when `SYNC_SCHEDULE` is set; otherwise the container runs once and exits.

**Tech Stack:** Python 3.12, httpx 0.27, apscheduler 3.10, pytest + pytest-asyncio + respx (dev).

## Global Constraints

- Python 3.12 (`str | None` union syntax, no `Optional`)
- `httpx>=0.27.0`, `apscheduler>=3.10.0` (runtime)
- `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`, `respx>=0.21.0` (dev only — not in Docker image)
- Base API URL: `https://api.ui.com`, auth header: `X-API-Key: <key>`
- Retry: 3 attempts, delays 1s → 2s → 4s; catch `httpx.HTTPStatusError`, `httpx.NetworkError`, `httpx.TimeoutException`
- Tag match: `SYNC_TAG` is a substring of rule `name` OR `comment`
- Identity key for rule matching: `name` field (exact match)
- `fwd_ip` on all WAN rules must equal `LOCAL_ROUTER_LAN_ADR`
- `DRY_RUN=true` skips all POST/PUT/DELETE to WAN — log `[DRY RUN] would <ACTION>: <name>` instead
- All tests run from project root: `pytest tests/`

---

### Task 1: Project Scaffold

**Files:**
- Create: `sync.py` (stub)
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/test_sync.py` (stub)

**Interfaces:**
- Produces: `docker build -t unifi-sync .` exits 0

- [ ] **Step 1: Create `requirements.txt`**

```
httpx>=0.27.0
apscheduler>=3.10.0
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0.0
pytest-asyncio>=0.23.0
respx>=0.21.0
```

- [ ] **Step 3: Create `Dockerfile`**

```dockerfile
FROM python:3.12-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sync.py .
CMD ["python", "sync.py"]
```

- [ ] **Step 4: Create `docker-compose.yml`**

```yaml
services:
  unifi-sync:
    build: .
    env_file: .env
    restart: unless-stopped
```

- [ ] **Step 5: Create `.env.example`**

```
WAN_ROUTER_API_KEY=your_wan_api_key_here
LOCAL_ROUTER_API_KEY=your_local_api_key_here
LOCAL_ROUTER_LAN_ADR=192.168.1.1
DRY_RUN=false
SYNC_SCHEDULE=*/5 * * * *
SYNC_TAG=unifi-sync
```

- [ ] **Step 6: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 7: Create stub `sync.py`**

```python
# placeholder — implemented in subsequent tasks
```

- [ ] **Step 8: Create `tests/__init__.py`**

Empty file.

- [ ] **Step 9: Create stub `tests/test_sync.py`**

```python
# tests added in subsequent tasks
```

- [ ] **Step 10: Install dev deps**

Run: `pip install -r requirements-dev.txt`
Expected: All packages install without error.

- [ ] **Step 11: Verify Docker build**

Run: `docker build -t unifi-sync .`
Expected: Exits 0. Image tagged `unifi-sync`.

- [ ] **Step 12: Commit**

```bash
git add .
git commit -m "chore: project scaffold"
```

---

### Task 2: Config Loading

**Files:**
- Modify: `sync.py` — add `Config` dataclass + `load_config()`
- Modify: `tests/test_sync.py` — add config tests

**Interfaces:**
- Produces:
  - `Config` dataclass: `wan_api_key: str`, `local_api_key: str`, `local_router_lan_adr: str`, `dry_run: bool`, `sync_schedule: str | None`, `sync_tag: str`
  - `load_config() -> Config` — reads env vars, calls `sys.exit(1)` if any required var is missing or empty

- [ ] **Step 1: Write failing tests in `tests/test_sync.py`**

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest tests/test_sync.py -v`
Expected: `ImportError` — `load_config` not defined.

- [ ] **Step 3: Replace `sync.py` with config implementation**

```python
import asyncio
import logging
import os
import sys
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://api.ui.com"


@dataclass
class Config:
    wan_api_key: str
    local_api_key: str
    local_router_lan_adr: str
    dry_run: bool
    sync_schedule: str | None
    sync_tag: str


def load_config() -> Config:
    wan_key = os.environ.get("WAN_ROUTER_API_KEY", "")
    local_key = os.environ.get("LOCAL_ROUTER_API_KEY", "")
    lan_adr = os.environ.get("LOCAL_ROUTER_LAN_ADR", "")
    missing = [
        name for name, val in [
            ("WAN_ROUTER_API_KEY", wan_key),
            ("LOCAL_ROUTER_API_KEY", local_key),
            ("LOCAL_ROUTER_LAN_ADR", lan_adr),
        ]
        if not val
    ]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)
    return Config(
        wan_api_key=wan_key,
        local_api_key=local_key,
        local_router_lan_adr=lan_adr,
        dry_run=os.environ.get("DRY_RUN", "false").lower() == "true",
        sync_schedule=os.environ.get("SYNC_SCHEDULE") or None,
        sync_tag=os.environ.get("SYNC_TAG", "unifi-sync"),
    )
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `pytest tests/test_sync.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add sync.py tests/test_sync.py
git commit -m "feat: config loading with env var validation"
```

---

### Task 3: UnifiClient — HTTP, Discovery, and Port Forward CRUD

**Files:**
- Modify: `sync.py` — add `UnifiClient` class
- Modify: `tests/test_sync.py` — add client tests

**Interfaces:**
- Consumes: `BASE_URL`, `asyncio`, `log` from Task 2's `sync.py`
- Produces:
  - `UnifiClient(api_key: str, label: str)` — stores `host_id: str | None = None`, `site_id: str | None = None`
  - `await client._request_with_retry(method: str, url: str, **kwargs) -> dict`
  - `await client.discover() -> None` — sets `host_id` and `site_id`; `sys.exit(1)` if hosts or sites empty
  - `await client.list_port_forwards() -> list[dict]`
  - `await client.create_port_forward(rule: dict) -> dict`
  - `await client.update_port_forward(rule_id: str, rule: dict) -> dict`
  - `await client.delete_port_forward(rule_id: str) -> None`
  - `await client.close() -> None`

- [ ] **Step 1: Add client tests to `tests/test_sync.py`**

```python
import httpx
import respx
from unittest.mock import AsyncMock, patch


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
```

- [ ] **Step 2: Run tests — verify new tests fail**

Run: `pytest tests/test_sync.py -v`
Expected: New tests fail with `ImportError` — `UnifiClient` not defined. Existing 4 tests still pass.

- [ ] **Step 3: Add `UnifiClient` to `sync.py` (after `load_config`)**

```python
import httpx


class UnifiClient:
    def __init__(self, api_key: str, label: str) -> None:
        self.api_key = api_key
        self.label = label
        self.host_id: str | None = None
        self.site_id: str | None = None
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"X-API-Key": api_key},
            timeout=30.0,
        )

    async def _request_with_retry(self, method: str, url: str, **kwargs) -> dict:
        delays = [1, 2, 4]
        last_exc: Exception | None = None
        for attempt, delay in enumerate(delays + [None], start=1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                if delay is None:
                    break
                log.warning(
                    "[%s] Request failed (attempt %d/3): %s. Retrying in %ds...",
                    self.label, attempt, exc, delay,
                )
                await asyncio.sleep(delay)
        raise last_exc

    async def discover(self) -> None:
        data = await self._request_with_retry("GET", "/v1/hosts")
        hosts = data.get("data", [])
        if not hosts:
            log.error("[%s] No hosts found. Check API key permissions.", self.label)
            sys.exit(1)
        self.host_id = hosts[0]["id"]
        log.info("[%s] Using host: %s", self.label, self.host_id)

        site_data = await self._request_with_retry(
            "GET",
            f"/v1/connector/consoles/{self.host_id}/proxy/network/v1/sites",
        )
        sites = site_data.get("data", [])
        if not sites:
            log.error("[%s] No sites found.", self.label)
            sys.exit(1)
        self.site_id = sites[0]["name"]
        log.info("[%s] Using site: %s", self.label, self.site_id)

    def _pf_url(self, suffix: str = "") -> str:
        return (
            f"/v1/connector/consoles/{self.host_id}"
            f"/proxy/network/api/s/{self.site_id}/rest/portforward{suffix}"
        )

    async def list_port_forwards(self) -> list[dict]:
        data = await self._request_with_retry("GET", self._pf_url())
        return data.get("data", [])

    async def create_port_forward(self, rule: dict) -> dict:
        return await self._request_with_retry("POST", self._pf_url(), json=rule)

    async def update_port_forward(self, rule_id: str, rule: dict) -> dict:
        return await self._request_with_retry("PUT", self._pf_url(f"/{rule_id}"), json=rule)

    async def delete_port_forward(self, rule_id: str) -> None:
        await self._request_with_retry("DELETE", self._pf_url(f"/{rule_id}"))

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Run all tests — verify they pass**

Run: `pytest tests/test_sync.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add sync.py tests/test_sync.py
git commit -m "feat: UnifiClient with discovery, CRUD, and retry"
```

---

### Task 4: Sync Logic, Main Entrypoint, and Scheduling

**Files:**
- Modify: `sync.py` — add `is_tagged`, `make_wan_rule`, `rules_differ`, `sync()`, `main()`, `__main__` block
- Modify: `tests/test_sync.py` — add sync and scheduling tests

**Interfaces:**
- Consumes: `UnifiClient` (Task 3), `Config` (Task 2)
- Produces: complete, runnable `sync.py`

- [ ] **Step 1: Add sync and scheduling tests to `tests/test_sync.py`**

```python
from unittest.mock import AsyncMock, MagicMock


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
```

- [ ] **Step 2: Run tests — verify new tests fail**

Run: `pytest tests/test_sync.py -v`
Expected: New tests fail — `is_tagged`, `make_wan_rule`, `rules_differ`, `sync` not defined. All previous tests still pass.

- [ ] **Step 3: Add sync helpers to `sync.py` (after `UnifiClient`)**

```python
def is_tagged(rule: dict, tag: str) -> bool:
    return tag in rule.get("name", "") or tag in rule.get("comment", "")


def make_wan_rule(local_rule: dict, fwd_ip: str) -> dict:
    return {
        "name": local_rule["name"],
        "proto": local_rule["proto"],
        "dst_port": local_rule["dst_port"],
        "fwd_port": local_rule["fwd_port"],
        "fwd_ip": fwd_ip,
        "enabled": local_rule.get("enabled", True),
    }


def rules_differ(local_rule: dict, wan_rule: dict) -> bool:
    return any(
        local_rule.get(f) != wan_rule.get(f)
        for f in ("proto", "dst_port", "fwd_port", "enabled")
    )


async def sync(local: "UnifiClient", wan: "UnifiClient", config: Config) -> None:
    log.info("Starting sync...")
    local_rules = await local.list_port_forwards()
    wan_rules = await wan.list_port_forwards()

    tagged_local = {r["name"]: r for r in local_rules if is_tagged(r, config.sync_tag)}
    tagged_wan = {r["name"]: r for r in wan_rules if is_tagged(r, config.sync_tag)}

    local_names = set(tagged_local)
    wan_names = set(tagged_wan)
    created = deleted = updated = 0

    for name in local_names - wan_names:
        rule = make_wan_rule(tagged_local[name], config.local_router_lan_adr)
        if config.dry_run:
            log.info("[DRY RUN] would CREATE: %s", name)
        else:
            try:
                await wan.create_port_forward(rule)
                log.info("CREATED: %s", name)
                created += 1
            except Exception as exc:
                log.error("Failed to CREATE %s: %s", name, exc)

    for name in wan_names - local_names:
        wan_rule = tagged_wan[name]
        if config.dry_run:
            log.info("[DRY RUN] would DELETE: %s", name)
        else:
            try:
                await wan.delete_port_forward(wan_rule["_id"])
                log.info("DELETED: %s", name)
                deleted += 1
            except Exception as exc:
                log.error("Failed to DELETE %s: %s", name, exc)

    for name in local_names & wan_names:
        if rules_differ(tagged_local[name], tagged_wan[name]):
            rule = make_wan_rule(tagged_local[name], config.local_router_lan_adr)
            if config.dry_run:
                log.info("[DRY RUN] would UPDATE: %s", name)
            else:
                try:
                    await wan.update_port_forward(tagged_wan[name]["_id"], rule)
                    log.info("UPDATED: %s", name)
                    updated += 1
                except Exception as exc:
                    log.error("Failed to UPDATE %s: %s", name, exc)

    log.info("Sync complete. created=%d deleted=%d updated=%d", created, deleted, updated)
```

- [ ] **Step 4: Add `main()` and entrypoint to `sync.py`**

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


async def main() -> None:
    config = load_config()
    local = UnifiClient(config.local_api_key, "LOCAL")
    wan = UnifiClient(config.wan_api_key, "WAN")
    try:
        await local.discover()
        await wan.discover()

        async def run_sync() -> None:
            try:
                await sync(local, wan, config)
            except Exception:
                log.exception("Sync run failed")

        if config.sync_schedule:
            scheduler = AsyncIOScheduler()
            scheduler.add_job(run_sync, CronTrigger.from_crontab(config.sync_schedule))
            scheduler.start()
            log.info("Scheduler started with cron: %s", config.sync_schedule)
            await asyncio.Event().wait()
        else:
            await run_sync()
    finally:
        await local.close()
        await wan.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Run all tests — verify they pass**

Run: `pytest tests/test_sync.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Verify Docker image builds cleanly**

Run: `docker build -t unifi-sync .`
Expected: Exits 0.

- [ ] **Step 7: Smoke test the image entrypoint (missing env vars → exit 1)**

Run: `docker run --rm unifi-sync`
Expected: Container exits with code 1 and logs `Missing required env vars: WAN_ROUTER_API_KEY, LOCAL_ROUTER_API_KEY, LOCAL_ROUTER_LAN_ADR`

- [ ] **Step 8: Commit**

```bash
git add sync.py tests/test_sync.py
git commit -m "feat: sync logic, main entrypoint, and scheduling"
```
