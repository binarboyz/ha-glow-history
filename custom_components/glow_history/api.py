"""Minimal async client for the Hildebrand Glowmarkt API."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import API_BASE, APPLICATION_ID

_LOGGER = logging.getLogger(__name__)

RETRIES = 4
TIMEOUT = aiohttp.ClientTimeout(total=45)


class GlowAuthError(Exception):
    """Credentials were rejected."""


class GlowApiError(Exception):
    """The API could not be reached or returned something unexpected."""


class GlowNotFound(GlowApiError):
    """HTTP 404: Glowmarkt has nothing for this request (e.g. before your data starts)."""


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class GlowApi:
    """Talks to api.glowmarkt.com with the user's Bright login."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None
        self._token_exp: float = 0

    async def authenticate(self) -> None:
        """Log in and store a token."""
        last_err: Exception | None = None
        for attempt in range(RETRIES):
            try:
                async with self._session.post(
                    f"{API_BASE}/auth",
                    json={"username": self._username, "password": self._password},
                    headers={"applicationId": APPLICATION_ID},
                    timeout=TIMEOUT,
                ) as resp:
                    if resp.status in (401, 403):
                        raise GlowAuthError("Bright login rejected")
                    if resp.status >= 500:
                        raise GlowApiError(f"Auth returned HTTP {resp.status}")
                    data = await resp.json(content_type=None)
                if not isinstance(data, dict) or not data.get("valid") or not data.get("token"):
                    raise GlowAuthError("Bright login rejected")
                self._token = data["token"]
                self._token_exp = float(data.get("exp") or time.time() + 3 * 86400)
                return
            except GlowAuthError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, GlowApiError, ValueError) as err:
                last_err = err
                await asyncio.sleep(2 * (attempt + 1))
        raise GlowApiError(f"Could not log in to Glowmarkt: {last_err}")

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        """GET with retries (Glowmarkt drops connections now and then)."""
        if not self._token or self._token_exp - time.time() < 3600:
            await self.authenticate()
        last_err: Exception | None = None
        reauthed = False
        for attempt in range(RETRIES):
            try:
                async with self._session.get(
                    f"{API_BASE}{path}",
                    params=params,
                    headers={"applicationId": APPLICATION_ID, "token": self._token or ""},
                    timeout=TIMEOUT,
                ) as resp:
                    if resp.status in (401, 403) and not reauthed:
                        reauthed = True
                        await self.authenticate()
                        continue
                    if resp.status == 404:
                        raise GlowNotFound(f"GET {path} returned HTTP 404")
                    if 400 <= resp.status < 500:
                        # Client errors won't fix themselves on retry.
                        raise GlowNotFound(f"GET {path} returned HTTP {resp.status}")
                    if resp.status >= 500:
                        raise GlowApiError(f"GET {path} returned HTTP {resp.status}")
                    return await resp.json(content_type=None)
            except (GlowAuthError, GlowNotFound):
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, GlowApiError, ValueError) as err:
                last_err = err
                _LOGGER.debug("GET %s failed (attempt %s): %s", path, attempt + 1, err)
                await asyncio.sleep(2 * (attempt + 1))
        raise GlowApiError(f"GET {path} failed: {last_err}")

    async def get_resources(self) -> dict[str, str]:
        """Return {classifier: resourceId} across all virtual entities."""
        found: dict[str, str] = {}
        entities = await self._get("/virtualentity")
        for ve in entities or []:
            ve_id = ve.get("veId") if isinstance(ve, dict) else None
            if not ve_id:
                continue
            detail = await self._get(f"/virtualentity/{ve_id}/resources")
            for res in (detail or {}).get("resources", []):
                cls, rid = res.get("classifier"), res.get("resourceId")
                if cls and rid and cls not in found:
                    found[cls] = rid
        return found

    async def catchup(self, resource_id: str) -> None:
        """Ask Glowmarkt to pull the latest data from the DCC (best effort)."""
        try:
            await self._get(f"/resource/{resource_id}/catchup")
        except GlowApiError as err:
            _LOGGER.debug("Catchup for %s failed: %s", resource_id, err)

    async def readings(self, resource_id: str, start: datetime, end: datetime) -> dict[int, float]:
        """Half-hourly kWh readings {epoch_seconds: kWh} between start and end (UTC).

        A 404 means Glowmarkt holds no data for that period, which happens for
        periods before your meter's history begins. That's treated as empty.
        """
        try:
            data = await self._get(
                f"/resource/{resource_id}/readings",
                {
                    "from": _fmt(start),
                    "to": _fmt(end),
                    "period": "PT30M",
                    "function": "sum",
                    "offset": "0",
                },
            )
        except GlowNotFound as err:
            _LOGGER.debug("No readings for %s %s-%s: %s", resource_id, start, end, err)
            return {}
        if not isinstance(data, dict) or "data" not in data:
            raise GlowApiError("Unexpected readings response")
        out: dict[int, float] = {}
        for item in data["data"] or []:
            if isinstance(item, list) and len(item) >= 2 and item[1] is not None:
                out[int(item[0])] = float(item[1])
        return out
