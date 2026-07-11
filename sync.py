import asyncio
import logging
import os
import sys
from dataclasses import dataclass

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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
    wan_host_id: str | None
    local_host_id: str | None


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
        wan_host_id=os.environ.get("WAN_ROUTER_HOST_ID") or None,
        local_host_id=os.environ.get("LOCAL_ROUTER_HOST_ID") or None,
    )


class UnifiClient:
    def __init__(self, api_key: str, label: str, host_id: str | None = None) -> None:
        self.api_key = api_key
        self.label = label
        self.host_id: str | None = host_id
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
        assert last_exc is not None
        raise last_exc

    async def discover(self) -> None:
        if self.host_id:
            log.info("[%s] Using host (override): %s", self.label, self.host_id)
        else:
            data = await self._request_with_retry("GET", "/v1/hosts")
            hosts = data.get("data", [])
            if not hosts:
                log.error("[%s] No hosts found. Check API key permissions.", self.label)
                sys.exit(1)
            self.host_id = hosts[0]["id"]
            log.info("[%s] Using host: %s", self.label, self.host_id)

        site_data = await self._request_with_retry(
            "GET",
            f"/v1/connector/consoles/{self.host_id}/proxy/network/api/self/sites",
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


async def sync(local: UnifiClient, wan: UnifiClient, config: Config) -> None:
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


async def main() -> None:
    config = load_config()
    local = UnifiClient(config.local_api_key, "LOCAL", host_id=config.local_host_id)
    wan = UnifiClient(config.wan_api_key, "WAN", host_id=config.wan_host_id)
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
