import logging
from datetime import timedelta, datetime, timezone
from homeassistant.helpers.storage import Store

import async_timeout
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, STATUS, CONFIG, SYSTEM, HOSTNAME
from .apex import Apex

logger = logging.getLogger(__name__)


class ApexDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, user: str, password: str, deviceip: str, update_interval: float):
        self._hass = hass
        self.deviceip: str = deviceip
        self.apex: Apex = Apex(user, password, deviceip)
        self._available: bool = True
        self._store = Store(hass, 1, f"{DOMAIN}_{deviceip}_dlog")
        self._dlog_state = {
            "totals": {},        # did -> float
            "last_seen": {},     # did -> int epoch seconds
        }
        self._dlog_loaded = False


        super().__init__(
            hass,
            logger,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self):
        try:
            async with async_timeout.timeout(30):
                await self._async_load_dlog_state()

                status = await self._hass.async_add_executor_job(self.apex.status)
                config = await self._hass.async_add_executor_job(self.apex.config)

                # ---- DLOG ingestion ----
                # Choose a small overlap window; 2 days is conservative.
                days = 2

                # If we have any last_seen timestamps, start from that date (minus overlap).
                # Otherwise, start "today" in UTC (Apex will return recent within days anyway).
                last_seen_any = 0
                if self._dlog_state["last_seen"]:
                    last_seen_any = max(int(v) for v in self._dlog_state["last_seen"].values() if v)

                if last_seen_any > 0:
                    sdate = self._sdate_from_epoch(last_seen_any)
                else:
                    now = int(datetime.now(tz=timezone.utc).timestamp())
                    sdate = self._sdate_from_epoch(now)

                dlog = await self._hass.async_add_executor_job(self.apex.dlog, days, sdate)
                records = (((dlog or {}).get("dlog") or {}).get("record")) or []
                if records:
                    before = dict(self._dlog_state["last_seen"])
                    self._ingest_dlog_records(records)
                    if self._dlog_state["last_seen"] != before:
                        await self._async_save_dlog_state()

                data = {
                    STATUS: status,
                    CONFIG: config,
                    "dlog_totals": dict(self._dlog_state["totals"]),
                }
                logger.debug("refreshing now")
                return data
        except Exception as ex:
            self._available = False
            logger.warning(str(ex))
            logger.warning("error communicating with Apex for %s", self.deviceip)
            raise UpdateFailed(f"error communicating with Apex for {self.deviceip}") from ex


    async def _async_load_dlog_state(self) -> None:
        if self._dlog_loaded:
            return
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            # tolerate partial/older formats
            self._dlog_state["totals"] = stored.get("totals", {}) or {}
            self._dlog_state["last_seen"] = stored.get("last_seen", {}) or {}
        self._dlog_loaded = True

    async def _async_save_dlog_state(self) -> None:
        await self._store.async_save(self._dlog_state)

    def _sdate_from_epoch(self, epoch_seconds: int) -> str:
        # Apex expects YYMMDD (example: 260101). We'll use UTC date by default.
        dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
        return dt.strftime("%y%m%d")

    def _ingest_dlog_records(self, records: list[dict]) -> None:
        """
        records: list of {"date": int, "did": str, "value": float}
        Mutates self._dlog_state totals + last_seen.
        """
        totals = self._dlog_state["totals"]
        last_seen = self._dlog_state["last_seen"]

        # Process in chronological order so last_seen updates correctly
        records_sorted = sorted(records, key=lambda r: int(r.get("date", 0)))

        for r in records_sorted:
            did = r.get("did")
            if not did:
                continue
            ts = int(r.get("date", 0))
            val = r.get("value")
            try:
                val_f = float(val)
            except (TypeError, ValueError):
                continue

            prev_ts = int(last_seen.get(did, 0) or 0)
            if ts <= prev_ts:
                # already processed (or older)
                continue

            totals[did] = float(totals.get(did, 0.0) or 0.0) + val_f
            last_seen[did] = ts


    @property
    def hostname(self) -> str:
        return self.data[STATUS][SYSTEM][HOSTNAME]
