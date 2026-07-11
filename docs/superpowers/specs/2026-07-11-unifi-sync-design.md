# UniFi Port Forward Sync — Design Spec
Date: 2026-07-11

## Problem

Two UniFi routers (LOCAL, WAN) managed via UniFi Cloud. Port forwarding rules defined on LOCAL must be mirrored to WAN, where the destination IP becomes the WAN router's assigned address for the local network. Rules are tagged to distinguish managed rules from manually-created ones.

## Scope

Docker container. Python. Reads port forward rules from LOCAL router, syncs tagged rules to WAN router via UniFi Cloud API.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `WAN_ROUTER_API_KEY` | yes | — | API key for WAN router (api.ui.com) |
| `LOCAL_ROUTER_API_KEY` | yes | — | API key for LOCAL router (api.ui.com) |
| `LOCAL_ROUTER_LAN_ADR` | yes | — | IP WAN router assigns to local router; used as `fwd_ip` on WAN rules |
| `DRY_RUN` | no | `false` | Log intended writes, skip all POST/PUT/DELETE to WAN |
| `SYNC_SCHEDULE` | no | — | Cron expression (e.g. `*/5 * * * *`). If absent/empty, run once and exit. |
| `SYNC_TAG` | no | `unifi-sync` | String matched against rule `name` or `comment` to identify managed rules |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              sync.py (async)                │
│                                             │
│  UnifiClient(LOCAL_KEY)  UnifiClient(WAN_KEY)│
│         │                      │            │
│   auto-discover           auto-discover     │
│   hostId, siteId          hostId, siteId    │
│         │                      │            │
│         └──────── sync() ──────┘            │
│                     │                       │
│              APScheduler (cron)             │
│              or run-once + exit             │
└─────────────────────────────────────────────┘
         │                      │
  api.ui.com (LOCAL key)  api.ui.com (WAN key)
```

Single script, two `UnifiClient` instances, one `sync()` function.

---

## API Interaction

**Base URL:** `https://api.ui.com`

**Auth:** `X-API-Key: <key>` header on all requests.

**Console discovery (per client):**
```
GET /v1/hosts
→ pick hosts[0].id as hostId
```

**Site discovery (per client):**
```
GET /v1/connector/consoles/{hostId}/proxy/network/v1/sites
→ pick sites[0].name as siteId
```

**Port forward CRUD (legacy endpoint via proxy):**
```
GET    /v1/connector/consoles/{hostId}/proxy/network/api/s/{siteId}/rest/portforward
POST   /v1/connector/consoles/{hostId}/proxy/network/api/s/{siteId}/rest/portforward
PUT    /v1/connector/consoles/{hostId}/proxy/network/api/s/{siteId}/rest/portforward/{id}
DELETE /v1/connector/consoles/{hostId}/proxy/network/api/s/{siteId}/rest/portforward/{id}
```

Port forward rule fields used:
| Field | Description |
|---|---|
| `_id` | Rule ID (WAN only, for PUT/DELETE) |
| `name` | Rule name; matched against `SYNC_TAG` |
| `comment` | Also checked for `SYNC_TAG` match |
| `proto` | `tcp`, `udp`, or `tcp_udp` |
| `dst_port` | External port (identity key) |
| `fwd_port` | Internal port forwarded to |
| `fwd_ip` | Destination IP; set to `LOCAL_ROUTER_LAN_ADR` on WAN |
| `enabled` | Boolean |

---

## Sync Logic

Runs as `async def sync()`:

1. Fetch all LOCAL port forward rules → filter: `SYNC_TAG in rule.name or SYNC_TAG in rule.get("comment", "")`
2. Fetch all WAN port forward rules → same filter
3. Build lookup dicts keyed by `name`
4. **CREATE:** LOCAL-only names → POST to WAN, `fwd_ip = LOCAL_ROUTER_LAN_ADR`
5. **DELETE:** WAN-only names → DELETE from WAN
6. **UPDATE:** names in both → if `proto`, `dst_port`, `fwd_port`, or `enabled` differ → PUT to WAN

`DRY_RUN=true`: log `[DRY RUN] would CREATE/DELETE/UPDATE ...`, skip all writes.

---

## Scheduling

```python
if SYNC_SCHEDULE:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(sync, CronTrigger.from_crontab(SYNC_SCHEDULE))
    scheduler.start()
    asyncio.get_event_loop().run_forever()
else:
    asyncio.run(sync())
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Discovery fails (hosts or sites empty) | Fatal — log + `sys.exit(1)` |
| API call fails (network/5xx) | Retry 3× with exponential backoff (1s, 2s, 4s), then raise |
| Single rule action fails | Log error, continue with remaining rules |
| Cron run throws unhandled exception | Log traceback, process stays alive, next run proceeds |
| Missing required env var | Fatal at startup — log which var is missing |

---

## Project Structure

```
unifi-sync/
├── sync.py              # all logic
├── requirements.txt     # httpx, apscheduler
├── Dockerfile           # python:3.12-alpine
├── docker-compose.yml   # example deployment
└── .env.example         # all env vars documented
```

---

## Docker

```dockerfile
FROM python:3.12-alpine
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sync.py .
CMD ["python", "sync.py"]
```

Image size: ~85MB. No privileged access required. Network: outbound HTTPS to `api.ui.com` only.

---

## Out of Scope

- Syncing firewall policies, ACL rules, or any other rule type
- WAN → LOCAL sync direction
- Multi-site support (first site used per console)
- Multi-console accounts (first host used per API key)
- Rule ordering preservation on WAN
