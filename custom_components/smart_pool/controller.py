"""Pool controller: reads source entities, tracks runtime and drives the pump."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calculations import (
    PumpInputs,
    chlorine_dose,
    classify_orp,
    classify_ph,
    combine_quality,
    decide_pump,
    guidance,
    ph_doses,
    recommended_runtime,
    split_at_midnight,
)
from .const import (
    CONF_AIR_TEMP_ENTITY,
    CONF_BACKWASH_DAYS,
    CONF_BACKWASH_HOURS,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CATCHUP_TIME,
    CONF_CHLORINE_STEP,
    CONF_CHLORINE_STRENGTH,
    CONF_DRY_RUN_POWER,
    CONF_FROST_TEMP,
    CONF_LAST_MEASUREMENT_ENTITY,
    CONF_MAX_RUNTIME,
    CONF_MIN_RUNTIME,
    CONF_ORP_ENTITY,
    CONF_PH_ENTITY,
    CONF_PUMP_ENERGY_ENTITY,
    CONF_PUMP_ENTITY,
    CONF_PUMP_FLOW,
    CONF_PUMP_POWER_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLAR_THRESHOLD,
    CONF_STALE_HOURS,
    CONF_VOLUME,
    CONF_WATER_TEMP_ENTITY,
    DEFAULT_MODE,
    DEFAULT_START_TIME,
    DEFAULTS,
    DOMAIN,
    DRY_RUN_CONFIRM_SECONDS,
    DRY_RUN_GRACE_SECONDS,
    EVENT_BACKWASH_DONE,
    EVENT_BACKWASH_DUE,
    EVENT_MEASUREMENT_STALE,
    EVENT_PUMP_FAULT,
    EVENT_PUMP_STARTED,
    EVENT_PUMP_STOPPED,
    EVENT_SMART_POOL,
    EVENT_WATER_QUALITY_CHANGED,
    MODE_AUTO,
    MODE_MANUAL,
    MODES,
    OPTIONAL_ENTITY_KEYS,
    QUALITY_UNKNOWN,
    STATUS_MANUAL,
    TICK_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


@dataclass(slots=True)
class PoolData:
    """Derived values exposed by the entities."""

    ph: float | None = None
    orp: float | None = None
    water_temp: float | None = None
    air_temp: float | None = None
    pump_power: float | None = None
    ph_status: str = QUALITY_UNKNOWN
    orp_status: str = QUALITY_UNKNOWN
    quality: str = QUALITY_UNKNOWN
    recommended_runtime: float = 0.0
    target_runtime: float = 0.0
    guidance: str = "unknown"
    runtime_today: float = 0.0
    remaining_runtime: float = 0.0
    backwash_hours: float = 0.0
    backwash_due: bool = False
    measurement_stale: bool = False
    last_measurement: datetime | None = None
    chlorine_dose: float = 0.0
    ph_minus_dose: float = 0.0
    ph_plus_dose: float = 0.0
    energy_today: float | None = None
    cost_today: float | None = None
    frost_risk: bool = False


def _parse_time(value: Any, fallback: str) -> time:
    parsed = dt_util.parse_time(str(value)) if value is not None else None
    return parsed or dt_util.parse_time(fallback) or time()


class SmartPoolController:
    """Keeps the state of one pool and optionally controls its pump."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the controller."""
        self.hass = hass
        self.entry = entry
        self.config: dict[str, Any] = {**DEFAULTS, **entry.data, **entry.options}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()

        # Persisted state
        self.mode: str = DEFAULT_MODE
        self.start_time: time = _parse_time(None, DEFAULT_START_TIME)
        self.target_runtime: float | None = None
        self.follow_recommendation: bool = True
        self.electricity_price: float = 0.30
        self.fault: bool = False
        self.last_backwash: datetime | None = None
        self._runtime_today_s: float = 0.0
        self._runtime_date: date | None = None
        self._backwash_s: float = 0.0
        self._energy_day_start: float | None = None
        self._energy_date: date | None = None

        # Volatile state
        self._last_accum: datetime | None = None
        self._pump_on: bool | None = None
        self._pump_on_since: datetime | None = None
        self._last_switch: datetime | None = None
        self._surplus_since: datetime | None = None
        self._deficit_since: datetime | None = None
        self._low_power_since: datetime | None = None
        self._initialized = False

        self.status: str = STATUS_MANUAL
        self.data = PoolData()

    # ------------------------------------------------------------------ setup

    @property
    def name(self) -> str:
        """Return the pool name."""
        return self.entry.title

    @property
    def pump_on(self) -> bool | None:
        """Return the last known pump state."""
        return self._pump_on

    def _entity(self, key: str) -> str | None:
        value = self.config.get(key)
        return value or None

    async def async_setup(self) -> None:
        """Restore state and start listening."""
        await self._async_restore()

        tracked = [
            entity_id
            for key in (
                CONF_PH_ENTITY,
                CONF_ORP_ENTITY,
                CONF_WATER_TEMP_ENTITY,
                CONF_PUMP_ENTITY,
                *OPTIONAL_ENTITY_KEYS,
            )
            if (entity_id := self._entity(key))
        ]
        self._unsubs.append(
            async_track_state_change_event(self.hass, tracked, self._handle_state_change)
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._handle_tick, timedelta(seconds=TICK_SECONDS))
        )
        await self.async_update()

    async def async_shutdown(self) -> None:
        """Stop listening and persist state."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._accumulate(dt_util.now())
        await self._store.async_save(self._data_to_save())

    async def _async_restore(self) -> None:
        stored = await self._store.async_load() or {}
        if stored.get("mode") in MODES:
            self.mode = stored["mode"]
        self.start_time = _parse_time(stored.get("start_time"), DEFAULT_START_TIME)
        if stored.get("target_runtime") is not None:
            self.target_runtime = float(stored["target_runtime"])
        self.follow_recommendation = bool(stored.get("follow_recommendation", True))
        self.electricity_price = float(stored.get("electricity_price", 0.30))
        self.fault = bool(stored.get("fault", False))
        self._runtime_today_s = float(stored.get("runtime_today_s", 0.0))
        self._backwash_s = float(stored.get("backwash_s", 0.0))
        if stored.get("energy_day_start") is not None:
            self._energy_day_start = float(stored["energy_day_start"])
        if raw := stored.get("runtime_date"):
            self._runtime_date = date.fromisoformat(raw)
        if raw := stored.get("energy_date"):
            self._energy_date = date.fromisoformat(raw)
        if raw := stored.get("last_backwash"):
            self.last_backwash = dt_util.parse_datetime(raw)

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "start_time": self.start_time.isoformat(),
            "target_runtime": self.target_runtime,
            "follow_recommendation": self.follow_recommendation,
            "electricity_price": self.electricity_price,
            "fault": self.fault,
            "runtime_today_s": self._runtime_today_s,
            "runtime_date": self._runtime_date.isoformat() if self._runtime_date else None,
            "backwash_s": self._backwash_s,
            "last_backwash": self.last_backwash.isoformat() if self.last_backwash else None,
            "energy_day_start": self._energy_day_start,
            "energy_date": self._energy_date.isoformat() if self._energy_date else None,
        }

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 30)

    # -------------------------------------------------------------- listeners

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Register an entity update callback."""
        self._listeners.append(update_callback)

        @callback
        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    @callback
    def _notify(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self.async_update())

    @callback
    def _handle_tick(self, now: datetime) -> None:
        self.hass.async_create_task(self.async_update())

    # ------------------------------------------------------------ user input

    async def async_set_mode(self, mode: str) -> None:
        """Change the operating mode."""
        if mode not in MODES:
            raise HomeAssistantError(f"Unknown mode {mode}")
        self.mode = mode
        self._schedule_save()
        await self.async_update()

    async def async_set_start_time(self, value: time) -> None:
        """Change the schedule start time."""
        self.start_time = value
        self._schedule_save()
        await self.async_update()

    async def async_set_target_runtime(self, value: float) -> None:
        """Set the daily target runtime in hours.

        Picking the current recommendation (as the pool card's "use
        recommendation" button does) re-enables following it; any other value
        pins the target.
        """
        self.target_runtime = value
        self.follow_recommendation = abs(value - self.data.recommended_runtime) < 0.25
        self._schedule_save()
        await self.async_update()

    async def async_set_follow_recommendation(self, follow: bool) -> None:
        """Let the target follow the recommendation or keep it fixed."""
        if not follow:
            # Freeze the target at what is currently in effect.
            self.target_runtime = self.data.target_runtime
        self.follow_recommendation = follow
        self._schedule_save()
        await self.async_update()

    async def async_set_electricity_price(self, value: float) -> None:
        """Change the electricity price per kWh."""
        self.electricity_price = value
        self._schedule_save()
        await self.async_update()

    async def async_backwash_done(self) -> None:
        """Reset the backwash counter."""
        self._accumulate(dt_util.now())
        self._backwash_s = 0.0
        self.last_backwash = dt_util.now()
        self._fire(EVENT_BACKWASH_DONE)
        self._schedule_save()
        await self.async_update()

    async def async_reset_fault(self) -> None:
        """Acknowledge a pump fault."""
        self.fault = False
        self._low_power_since = None
        self._schedule_save()
        await self.async_update()

    # ----------------------------------------------------------------- update

    async def async_update(self) -> None:
        """Recalculate everything and act on the pump if needed."""
        async with self._lock:
            now = dt_util.now()
            self._accumulate(now)
            self._read_pump(now)
            self._refresh(now)
            self._check_dry_run(now)
            await self._control_pump(now)
            self._initialized = True
            self._schedule_save()
        self._notify()

    def _state_float(self, key: str) -> float | None:
        entity_id = self._entity(key)
        if entity_id is None or (state := self.hass.states.get(entity_id)) is None:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _roll_day(self, now: datetime) -> None:
        today = now.date()
        if self._runtime_date != today:
            self._runtime_today_s = 0.0
            self._runtime_date = today

    def _accumulate(self, now: datetime) -> None:
        """Add pump on-time since the last call to the counters."""
        last, self._last_accum = self._last_accum, now
        self._roll_day(now)
        if last is None or not self._pump_on:
            return
        before, after = split_at_midnight(last, now)
        if after:
            self._runtime_today_s = after
        else:
            self._runtime_today_s += before
        self._backwash_s += before + after

    def _read_pump(self, now: datetime) -> None:
        entity_id = self._entity(CONF_PUMP_ENTITY)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state not in (STATE_ON, STATE_OFF):
            pump_on = None
        else:
            pump_on = state.state == STATE_ON
        if pump_on and not self._pump_on:
            self._pump_on_since = now
        elif not pump_on:
            self._pump_on_since = None
        self._pump_on = pump_on

    def _refresh(self, now: datetime) -> None:
        cfg = self.config
        data = self.data
        prev_quality = data.quality
        prev_stale = data.measurement_stale
        prev_backwash = data.backwash_due

        data.ph = self._state_float(CONF_PH_ENTITY)
        data.orp = self._state_float(CONF_ORP_ENTITY)
        data.water_temp = self._state_float(CONF_WATER_TEMP_ENTITY)
        data.air_temp = self._state_float(CONF_AIR_TEMP_ENTITY)
        data.pump_power = self._state_float(CONF_PUMP_POWER_ENTITY)

        data.ph_status = classify_ph(data.ph)
        data.orp_status = classify_orp(data.orp)
        data.quality = combine_quality(data.ph_status, data.orp_status)

        volume = float(cfg[CONF_VOLUME])
        data.recommended_runtime = recommended_runtime(
            data.water_temp,
            volume_m3=volume,
            pump_flow_m3h=float(cfg[CONF_PUMP_FLOW]),
            orp_status=data.orp_status,
            min_hours=float(cfg[CONF_MIN_RUNTIME]),
            max_hours=float(cfg[CONF_MAX_RUNTIME]),
        )
        if self.follow_recommendation or self.target_runtime is None:
            data.target_runtime = data.recommended_runtime
        else:
            data.target_runtime = self.target_runtime
        data.runtime_today = round(self._runtime_today_s / 3600, 2)
        data.remaining_runtime = round(max(0.0, data.target_runtime - data.runtime_today), 2)

        data.chlorine_dose = chlorine_dose(
            data.orp,
            volume_m3=volume,
            strength_percent=float(cfg[CONF_CHLORINE_STRENGTH]),
            step_ppm=float(cfg[CONF_CHLORINE_STEP]),
        )
        data.ph_minus_dose, data.ph_plus_dose = ph_doses(data.ph, volume_m3=volume)
        data.guidance = guidance(
            ph=data.ph,
            orp=data.orp,
            ph_minus_g=data.ph_minus_dose,
            ph_plus_g=data.ph_plus_dose,
            chlorine_g=data.chlorine_dose,
            language=self.hass.config.language,
        )

        # Backwash
        data.backwash_hours = round(self._backwash_s / 3600, 2)
        hours_limit = float(cfg[CONF_BACKWASH_HOURS])
        days_limit = float(cfg[CONF_BACKWASH_DAYS])
        due = hours_limit > 0 and data.backwash_hours >= hours_limit
        if self.last_backwash is not None and days_limit > 0:
            due = due or now - self.last_backwash >= timedelta(days=days_limit)
        data.backwash_due = due

        # Measurement age
        data.last_measurement = self._last_measurement()
        stale_hours = float(cfg[CONF_STALE_HOURS])
        data.measurement_stale = bool(
            stale_hours > 0
            and data.last_measurement is not None
            and now - data.last_measurement > timedelta(hours=stale_hours)
        )

        data.frost_risk = data.air_temp is not None and data.air_temp <= float(cfg[CONF_FROST_TEMP])

        self._refresh_energy(now)
        self._refresh_solar(now)

        if self._initialized:
            if data.quality != prev_quality and data.quality != QUALITY_UNKNOWN:
                self._fire(
                    EVENT_WATER_QUALITY_CHANGED,
                    quality=data.quality,
                    previous=prev_quality,
                    ph=data.ph,
                    orp=data.orp,
                )
            if data.measurement_stale and not prev_stale:
                self._fire(
                    EVENT_MEASUREMENT_STALE,
                    last_measurement=data.last_measurement.isoformat()
                    if data.last_measurement
                    else None,
                )
            if data.backwash_due and not prev_backwash:
                self._fire(EVENT_BACKWASH_DUE, pump_hours=data.backwash_hours)

    def _last_measurement(self) -> datetime | None:
        if entity_id := self._entity(CONF_LAST_MEASUREMENT_ENTITY):
            state = self.hass.states.get(entity_id)
            if state is not None and (parsed := dt_util.parse_datetime(state.state)):
                return dt_util.as_local(parsed)
            return None
        entity_id = self._entity(CONF_PH_ENTITY)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        return dt_util.as_local(state.last_reported)

    def _refresh_energy(self, now: datetime) -> None:
        data = self.data
        energy = self._state_float(CONF_PUMP_ENERGY_ENTITY)
        if energy is None:
            data.energy_today = None
            data.cost_today = None
            return
        today = now.date()
        if (
            self._energy_date != today
            or self._energy_day_start is None
            or energy < self._energy_day_start
        ):
            self._energy_day_start = energy
            self._energy_date = today
        data.energy_today = round(energy - self._energy_day_start, 3)
        data.cost_today = round(data.energy_today * self.electricity_price, 2)

    def _refresh_solar(self, now: datetime) -> None:
        cfg = self.config
        solar = self._state_float(CONF_SOLAR_POWER_ENTITY)
        surplus = solar is not None and solar >= float(cfg[CONF_SOLAR_THRESHOLD])
        if surplus and self._entity(CONF_BATTERY_SOC_ENTITY):
            soc = self._state_float(CONF_BATTERY_SOC_ENTITY)
            surplus = soc is not None and soc >= float(cfg[CONF_BATTERY_MIN_SOC])
        if surplus:
            self._deficit_since = None
            self._surplus_since = self._surplus_since or now
        else:
            self._surplus_since = None
            self._deficit_since = self._deficit_since or now

    def _check_dry_run(self, now: datetime) -> None:
        min_power = float(self.config[CONF_DRY_RUN_POWER])
        power = self.data.pump_power
        running_long_enough = (
            self._pump_on_since is not None
            and (now - self._pump_on_since).total_seconds() >= DRY_RUN_GRACE_SECONDS
        )
        if min_power <= 0 or power is None or not running_long_enough:
            self._low_power_since = None
            return
        if power >= min_power:
            self._low_power_since = None
            return
        self._low_power_since = self._low_power_since or now
        elapsed = (now - self._low_power_since).total_seconds()
        if elapsed >= DRY_RUN_CONFIRM_SECONDS and not self.fault:
            self.fault = True
            _LOGGER.warning(
                "%s: pump power %.0f W below %.0f W, possible dry run",
                self.name,
                power,
                min_power,
            )
            self._fire(EVENT_PUMP_FAULT, power=power, min_power=min_power)

    async def _control_pump(self, now: datetime) -> None:
        decision = decide_pump(
            PumpInputs(
                mode=self.mode,
                now=now,
                pump_on=self._pump_on,
                runtime_today_h=self.data.runtime_today,
                target_runtime_h=self.data.target_runtime,
                start_time=self.start_time,
                catchup_time=_parse_time(
                    self.config[CONF_CATCHUP_TIME], str(DEFAULTS[CONF_CATCHUP_TIME])
                ),
                solar_surplus_since=self._surplus_since,
                solar_deficit_since=self._deficit_since,
                air_temp=self.data.air_temp,
                frost_temp=float(self.config[CONF_FROST_TEMP]),
                fault=self.fault,
                last_switch=self._last_switch,
            )
        )
        self.status = decision.status
        if decision.turn_on is None or decision.turn_on == self._pump_on:
            return
        if self.mode == MODE_MANUAL:
            return

        service = SERVICE_TURN_ON if decision.turn_on else SERVICE_TURN_OFF
        entity_id = self._entity(CONF_PUMP_ENTITY)
        if entity_id is None:
            return
        self._last_switch = now
        try:
            await self.hass.services.async_call(
                entity_id.split(".", 1)[0],
                service,
                {ATTR_ENTITY_ID: entity_id},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("%s: could not switch pump %s: %s", self.name, entity_id, err)
            return
        self._fire(
            EVENT_PUMP_STARTED if decision.turn_on else EVENT_PUMP_STOPPED,
            reason=decision.status,
        )

    def card_entities(self) -> dict[str, Any]:
        """Entity mapping for the Modern Pool Card (custom:ha-pool-card)."""
        registry = er.async_get(self.hass)

        def own(platform: str, key: str) -> str | None:
            return registry.async_get_entity_id(platform, DOMAIN, f"{self.entry.entry_id}_{key}")

        mapping: dict[str, Any] = {
            "pump": self._entity(CONF_PUMP_ENTITY),
            "pump_power": self._entity(CONF_PUMP_POWER_ENTITY),
            "mode": own("select", "mode"),
            "target_mode": MODE_AUTO,
            "start_time": own("time", "start_time"),
            "target_runtime": own("number", "target_runtime"),
            "recommended_runtime": own("sensor", "recommended_runtime"),
            "runtime_today": own("sensor", "runtime_today"),
            "temperature": self._entity(CONF_WATER_TEMP_ENTITY),
            "ph": self._entity(CONF_PH_ENTITY),
            "orp": self._entity(CONF_ORP_ENTITY),
            "guidance": own("sensor", "guidance"),
            "last_measurement": own("sensor", "last_measurement"),
            "measurement_stale": own("binary_sensor", "measurement_stale"),
            "quality": own("sensor", "water_quality"),
            "energy_today": own("sensor", "energy_today"),
            "cost_today": own("sensor", "cost_today"),
            "solar_power": self._entity(CONF_SOLAR_POWER_ENTITY),
            "backwash": {
                "due": own("binary_sensor", "backwash_due"),
                "hours": own("sensor", "backwash_hours"),
                "last": own("sensor", "last_backwash"),
                "done_button": own("button", "backwash_done"),
            },
        }
        mapping["backwash"] = {k: v for k, v in mapping["backwash"].items() if v}
        return {k: v for k, v in mapping.items() if v}

    @callback
    def _fire(self, event_type: str, **extra: Any) -> None:
        self.hass.bus.async_fire(
            EVENT_SMART_POOL,
            {
                "entry_id": self.entry.entry_id,
                "name": self.name,
                "type": event_type,
                **extra,
            },
        )
