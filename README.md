# unifi-sync

Syncs tagged port forwarding rules from a LOCAL UniFi router to a WAN UniFi router via the UniFi Cloud API.

## Topology

```
                         Internet
                             │
                  ┌──────────────────────┐
                  │      WAN Router      │
                  │   (UDM / UCG / UGW)  │
                  │                      │
                  │  port forward rules  │ ◄── unifi-sync writes here
                  │  fwd_ip = LAN_ADR    │     (tagged rules only)
                  └──────────┬───────────┘
                             │
                   LOCAL_ROUTER_LAN_ADR
                   (e.g. 192.168.1.100)
                             │
                  ┌──────────────────────┐
                  │     LOCAL Router     │
                  │   (UDM / UCG / UGW)  │
                  │                      │
                  │  port forward rules  │ ◄── unifi-sync reads here
                  │  tagged "unifi-sync" │     (source of truth)
                  └──────────┬───────────┘
                             │
                       Local Network
                      192.168.x.x / 10.x.x.x
                             │
                    ┌────────────────┐
                    │  Your Devices  │
                    └────────────────┘

                  ┌──────────────────────┐
                  │    unifi-sync        │
                  │  (Docker container)  │
                  │                      │
                  │  reads LOCAL rules   │
                  │  writes WAN rules    │──── api.ui.com (HTTPS)
                  └──────────────────────┘
```

**How it works:** Rules tagged with `SYNC_TAG` (default: `unifi-sync`) on the LOCAL router are mirrored to the WAN router. The WAN router forwards external ports to `LOCAL_ROUTER_LAN_ADR`, which is the IP the WAN router has assigned to the LOCAL router. Untagged rules on either router are never touched.

**Two-way sync logic:**
- Tagged rule added on LOCAL → created on WAN
- Tagged rule deleted from LOCAL → deleted from WAN
- Tagged rule updated on LOCAL → updated on WAN
- Rules on WAN without a match on LOCAL → deleted from WAN

## Prerequisites

- Two UniFi routers (can be on different UniFi Cloud accounts)
- API key for each router — generate at **unifi.ui.com → Settings → API** on each account (or from the router's local console UI)
- Docker (or Python 3.12+)

## Setup

### 1. Tag rules on your LOCAL router

In UniFi Network → Firewall & Security → Port Forwarding, set the **Name** or **Description** of any rule you want synced to include `unifi-sync` (or your custom `SYNC_TAG`).

Example rule name: `unifi-sync http-server`

### 2. Find LOCAL_ROUTER_LAN_ADR

This is the IP the WAN router assigns to your LOCAL router's WAN interface. On the WAN router, check **Network → Clients** or **Devices** — look for your LOCAL router's IP address on the WAN-side network.

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
LOCAL_ROUTER_API_KEY=<api key from LOCAL router's account at unifi.ui.com>
WAN_ROUTER_API_KEY=<api key from WAN router's account at unifi.ui.com>
LOCAL_ROUTER_LAN_ADR=<WAN router's IP for the local router, e.g. 192.168.1.100>
DRY_RUN=false
# SYNC_SCHEDULE=*/5 * * * *   # uncomment for scheduled sync; absent = run once
SYNC_TAG=unifi-sync            # substring matched against rule name or description
```

### 4. Run

**One-shot sync (run once, then exit):**

```bash
docker compose run --rm unifi-sync
```

**Scheduled sync (runs on cron, stays alive):**

Uncomment `SYNC_SCHEDULE` in `.env`, then:

```bash
docker compose up -d
```

**Without Docker:**

```bash
pip install -r requirements.txt
python sync.py
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `LOCAL_ROUTER_API_KEY` | yes | — | API key for the LOCAL router (generate at unifi.ui.com or from the console UI) |
| `WAN_ROUTER_API_KEY` | yes | — | API key for the WAN router (generate from the WAN router's account or console UI) |
| `LOCAL_ROUTER_LAN_ADR` | yes | — | IP the WAN router assigns to the LOCAL router |
| `DRY_RUN` | no | `false` | Log intended changes without writing to WAN router |
| `SYNC_SCHEDULE` | no | — | Cron expression (e.g. `*/5 * * * *`). Absent = run once + exit. |
| `SYNC_TAG` | no | `unifi-sync` | Substring matched against rule name or description |
| `LOCAL_ROUTER_HOST_ID` | no | — | Pin LOCAL router by host ID (skips auto-discovery). Find in logs: `[LOCAL] Using host: <id>` |
| `WAN_ROUTER_HOST_ID` | no | — | Pin WAN router by host ID (skips auto-discovery). |

## Dry Run

Set `DRY_RUN=true` to preview what would change without writing anything:

```bash
DRY_RUN=true docker compose run --rm unifi-sync
```

Output example:
```
2026-07-11 13:00:00 INFO [DRY RUN] would CREATE: unifi-sync http-server
2026-07-11 13:00:00 INFO [DRY RUN] would DELETE: unifi-sync old-rule
2026-07-11 13:00:00 INFO Sync complete. created=0 deleted=0 updated=0
```

## Development

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## API

Uses the [UniFi Network API](https://developer.ui.com/network/) via `api.ui.com`. Auto-discovers console and site IDs from the provided API keys. Port forward rules are managed via the legacy proxy endpoint:

```
GET/POST/PUT/DELETE https://api.ui.com/v1/connector/consoles/{hostId}/proxy/network/api/s/{siteId}/rest/portforward
```

Requires outbound HTTPS to `api.ui.com` only — no VPN or local network access to the routers needed.
