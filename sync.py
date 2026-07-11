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
