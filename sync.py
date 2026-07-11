import asyncio
import logging
import os
import sys
from dataclasses import dataclass

import httpx

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
