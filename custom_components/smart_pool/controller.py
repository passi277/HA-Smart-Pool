"""Pool controller: reads source entities, tracks runtime and drives the pump."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
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
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calculations import (
    ForecastSummary,
    GuidanceInputs,
    PumpInputs,
    chlorine_dose,
    classify_orp,
    classify_ph,
    combine_quality,
    decide_pump,
    guidance,
    metal_ex_dose,
    ph_doses,
    recommended_runtime,
    refill_liters,
    split_at_midnight,
    summarize_forecast,
    surface_area,
    weather_extra_hours,
    weather_hint,
)
from .chemistry import (
    PRODUCT_CHLORINE,
    PRODUCT_METAL_EX,
    PRODUCT_PH_MINUS,
    PRODUCT_PH_PLUS,
    PRODUCT_SHOCK,
    PRODUCTS,
    Chemistry,
    low_stock_thresholds,
    product_name,
    shock_dose,
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
    CONF_HEAVY_RAIN,
    CONF_LAST_MEASUREMENT_ENTITY,
    CONF_MAX_RUNTIME,
    CONF_METAL_EX_FRESH,
    CONF_METAL_EX_HOURS,
    CONF_METAL_EX_POOL,
    CONF_MIN_RUNTIME,
    CONF_MOTION_ENTITY,
    CONF_ORP_ENTITY,
    CONF_OUTAGE_LIMIT,
    CONF_PH_ENTITY,
    CONF_PRESENCE_ENTITY,
    CONF_PROBE_DAYS,
    CONF_PUMP_ENERGY_ENTITY,
    CONF_PUMP_ENTITY,
    CONF_PUMP_FLOW,
    CONF_PUMP_POWER_ENTITY,
    CONF_PUMP_WIFI_ENTITY,
    CONF_RAIN_ENTITY,
    CONF_SAND_DAYS,
    CONF_SEALS_DAYS,
    CONF_SHOPPING_LIST_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLAR_THRESHOLD,
    CONF_STALE_HOURS,
    CONF_SURFACE,
    CONF_VISUAL_ENTITY,
    CONF_VOLUME,
    CONF_WATER_TEMP_ENTITY,
    CONF_WEATHER_ENTITY,
    DEFAULT_MODE,
    DEFAULT_REFILL_CM,
    DEFAULT_START_TIME,
    DEFAULTS,
    DOMAIN,
    DRY_RUN_CONFIRM_SECONDS,
    DRY_RUN_GRACE_SECONDS,
    EVENT_BACKWASH_DONE,
    EVENT_BACKWASH_DUE,
    EVENT_CONNECTION_UNSTABLE,
    EVENT_DOSE_LOGGED,
    EVENT_HEAVY_RAIN,
    EVENT_MAINTENANCE_DUE,
    EVENT_MEASUREMENT_STALE,
    EVENT_METAL_EX_ADDED,
    EVENT_METAL_EX_DONE,
    EVENT_MOTION_WHILE_AWAY,
    EVENT_PROBE_CHECK,
    EVENT_PROGRAM_DONE,
    EVENT_PROGRAM_STARTED,
    EVENT_PUMP_FAULT,
    EVENT_PUMP_STARTED,
    EVENT_PUMP_STOPPED,
    EVENT_REFILLED,
    EVENT_SEASON,
    EVENT_SMART_POOL,
    EVENT_STOCK_LOW,
    EVENT_VISUAL_FINDING,
    EVENT_WATER_QUALITY_CHANGED,
    EVENT_WEEKLY_REPORT,
    MODE_AUTO,
    MODE_MANUAL,
    MODE_WINTER,
    MODES,
    MOTION_COOLDOWN_SECONDS,
    OPTIONAL_ENTITY_KEYS,
    QUALITY_UNKNOWN,
    STATUS_MANUAL,
    TICK_SECONDS,
    WEATHER_REFRESH_SECONDS,
)
from .programs import (
    DEFAULT_BOOST_HOURS,
    FOLLOW_UP_BACKWASH,
    FOLLOW_UP_MEASURE,
    PROGRAM_BOOST,
    PROGRAM_FOLLOW_UP,
    PROGRAM_HOURS,
    PROGRAM_NEW_FILL,
    ProgramState,
)
from .season import (
    SEASON_START,
    SEASON_SWIM,
    SEASON_WINTERIZE,
    TASK_PROBE,
    TASK_SAND,
    TASK_SEALS,
    Season,
    checklist,
)
from .stats import (
    EnergyCounter,
    WeekStats,
    build_report,
    parse_visual,
    report_due,
    solar_savings_rate,
    swim_label,
    swim_score,
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
    surface: float = 0.0
    rain_last_24h: float | None = None
    heavy_rain: bool = False
    forecast: ForecastSummary | None = None
    weather_extra_hours: float = 0.0
    weather_hint: str = "ok"
    fresh_water_l: float = 0.0
    metal_ex_dose: float = 0.0
    metal_ex_pool_dose: float = 0.0
    metal_ex_problem_dose: float = 0.0
    metal_ex_hours_left: float = 0.0
    program_hours_left: float = 0.0
    probe_suspect: bool = False
    low_stock: list[str] = field(default_factory=list)
    season: str = SEASON_SWIM
    maintenance_due: list[str] = field(default_factory=list)
    power_energy_today: float = 0.0
    solar_energy_today: float = 0.0
    solar_share_today: float | None = None
    solar_savings_today: float = 0.0
    solar_savings_rate: float = 0.0
    swim_score: int | None = None
    swim_label: str = "unknown"
    visual: list[str] = field(default_factory=list)
    visual_text: str | None = None
    motion_away: bool = False
    outages_today: int = 0
    connection_unstable: bool = False


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
        self.refill_cm: float = DEFAULT_REFILL_CM
        self.fresh_water_l: float = 0.0
        self.metal_ex_until: datetime | None = None
        self.metal_ex_backwash: bool = False
        self._rain_hours: dict[str, float] = {}
        self._rain_last_value: float | None = None
        self.chem = Chemistry()
        self.program = ProgramState()
        self.season = Season()
        self.todo_items: list[dict[str, Any]] = []
        self.week = WeekStats()
        self.last_report_date: date | None = None
        self.last_report_text: str | None = None
        self.last_report_details: dict[str, Any] = {}
        self.energy_today_counter = EnergyCounter()
        self._energy_counter_date: date | None = None
        self.outages_today: int = 0
        self._outage_date: date | None = None
        self.dose_product: str = PRODUCT_CHLORINE
        self.dose_amount: float = 0.0
        self.boost_hours: float = DEFAULT_BOOST_HOURS
        self.shock_done_at: datetime | None = None
        self._season_status: str | None = None
        self._due_tasks: set[str] = set()
        self._visual: set[str] = set()
        self._motion_fired: datetime | None = None
        self._last_energy_tick: datetime | None = None
        self._pump_state_raw: str | None = None

        # Volatile state
        self._forecast: ForecastSummary | None = None
        self._forecast_fetched: datetime | None = None
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
        self.refill_cm = float(stored.get("refill_cm", DEFAULT_REFILL_CM))
        self.fresh_water_l = float(stored.get("fresh_water_l", 0.0))
        if raw := stored.get("metal_ex_until"):
            self.metal_ex_until = dt_util.parse_datetime(raw)
        self.metal_ex_backwash = bool(stored.get("metal_ex_backwash", False))
        self._rain_hours = {k: float(v) for k, v in stored.get("rain_hours", {}).items()}
        if stored.get("rain_last_value") is not None:
            self._rain_last_value = float(stored["rain_last_value"])
        self.chem = Chemistry.from_dict(stored.get("chemistry"))
        self.program = ProgramState.from_dict(stored.get("program"))
        self.season = Season.from_dict(stored.get("season"))
        self.todo_items = list(stored.get("todo_items", []))
        self.week = WeekStats.from_dict(stored.get("week"))
        if raw := stored.get("last_report_date"):
            self.last_report_date = date.fromisoformat(raw)
        self.last_report_text = stored.get("last_report_text")
        self.last_report_details = dict(stored.get("last_report_details", {}))
        self.energy_today_counter = EnergyCounter.from_dict(stored.get("energy_today_counter"))
        if raw := stored.get("energy_counter_date"):
            self._energy_counter_date = date.fromisoformat(raw)
        self.outages_today = int(stored.get("outages_today", 0))
        if raw := stored.get("outage_date"):
            self._outage_date = date.fromisoformat(raw)
        if stored.get("dose_product") in PRODUCTS:
            self.dose_product = stored["dose_product"]
        self.dose_amount = float(stored.get("dose_amount", 0.0))
        self.boost_hours = float(stored.get("boost_hours", DEFAULT_BOOST_HOURS))
        self._season_status = stored.get("season_status")
        self._due_tasks = set(stored.get("due_tasks", []))
        if raw := stored.get("shock_done_at"):
            self.shock_done_at = dt_util.parse_datetime(raw)

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
            "refill_cm": self.refill_cm,
            "fresh_water_l": self.fresh_water_l,
            "metal_ex_until": self.metal_ex_until.isoformat() if self.metal_ex_until else None,
            "metal_ex_backwash": self.metal_ex_backwash,
            "rain_hours": self._rain_hours,
            "rain_last_value": self._rain_last_value,
            "chemistry": self.chem.as_dict(),
            "program": self.program.as_dict(),
            "season": self.season.as_dict(),
            "todo_items": self.todo_items,
            "week": self.week.as_dict(),
            "last_report_date": self.last_report_date.isoformat()
            if self.last_report_date
            else None,
            "last_report_text": self.last_report_text,
            "last_report_details": self.last_report_details,
            "energy_today_counter": self.energy_today_counter.as_dict(),
            "energy_counter_date": self._energy_counter_date.isoformat()
            if self._energy_counter_date
            else None,
            "outages_today": self.outages_today,
            "outage_date": self._outage_date.isoformat() if self._outage_date else None,
            "dose_product": self.dose_product,
            "dose_amount": self.dose_amount,
            "boost_hours": self.boost_hours,
            "shock_done_at": self.shock_done_at.isoformat() if self.shock_done_at else None,
            "season_status": self._season_status,
            "due_tasks": sorted(self._due_tasks),
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
        self.metal_ex_backwash = False
        self._fire(EVENT_BACKWASH_DONE)
        self._schedule_save()
        await self.async_update()

    async def async_set_refill_cm(self, value: float) -> None:
        """Set how many cm the refill button adds."""
        self.refill_cm = value
        self._schedule_save()
        await self.async_update()

    async def async_refilled(self) -> None:
        """Record a refill with fresh water of `refill_cm` centimetres."""
        liters = refill_liters(self.refill_cm, self.data.surface)
        self.fresh_water_l += liters
        self._fire(EVENT_REFILLED, cm=self.refill_cm, liters=round(liters))
        self._schedule_save()
        await self.async_update()

    async def async_metal_ex_added(self) -> None:
        """Metal remover was dosed (recommended amount): start the treatment."""
        await self.async_log_dose(PRODUCT_METAL_EX, None)

    def _start_metal_ex(self, now: datetime, ml: float) -> None:
        hours = float(self.config[CONF_METAL_EX_HOURS])
        self._fire(EVENT_METAL_EX_ADDED, ml=ml, hours=hours)
        self.fresh_water_l = 0.0
        self.metal_ex_until = now + timedelta(hours=hours) if hours > 0 else None
        self.metal_ex_backwash = False

    # ------------------------------------------------------------- chemistry

    def recommended_amount(self, product: str) -> float:
        """Suggested amount for a product right now."""
        cfg = self.config
        volume = float(cfg[CONF_VOLUME])
        strength = float(cfg[CONF_CHLORINE_STRENGTH])
        data = self.data
        if product == PRODUCT_CHLORINE:
            if data.chlorine_dose:
                return data.chlorine_dose
            return float(5 * round(volume * float(cfg[CONF_CHLORINE_STEP]) / (strength / 100) / 5))
        if product == PRODUCT_SHOCK:
            return shock_dose(volume, strength)
        if product == PRODUCT_PH_MINUS:
            return data.ph_minus_dose or float(5 * round(volume * 10 / 5))
        if product == PRODUCT_PH_PLUS:
            return data.ph_plus_dose or float(5 * round(volume * 10 / 5))
        if product == PRODUCT_METAL_EX:
            return data.metal_ex_dose or data.metal_ex_pool_dose
        return 0.0

    async def async_log_dose(self, product: str, amount: float | None) -> None:
        """Log a chemical addition (None = recommended amount)."""
        if product not in PRODUCTS:
            raise HomeAssistantError(f"Unknown product {product}")
        now = dt_util.now()
        value = self.recommended_amount(product) if amount is None else float(amount)
        entry = self.chem.add_dose(now, product, value, self.data.orp)
        if product == PRODUCT_METAL_EX:
            self._start_metal_ex(now, value)
        self._fire(EVENT_DOSE_LOGGED, product=product, amount=entry.amount)
        self._schedule_save()
        await self.async_update()

    async def async_log_selected_dose(self) -> None:
        """Log the product and amount chosen in the dose entities."""
        await self.async_log_dose(self.dose_product, self.dose_amount)

    async def async_set_dose_product(self, product: str) -> None:
        """Pick the product for the dose log; prefill the amount."""
        if product not in PRODUCTS:
            raise HomeAssistantError(f"Unknown product {product}")
        self.dose_product = product
        self.dose_amount = self.recommended_amount(product)
        self._schedule_save()
        await self.async_update()

    async def async_set_dose_amount(self, value: float) -> None:
        """Set the amount for the dose log."""
        self.dose_amount = value
        self._schedule_save()
        await self.async_update()

    async def async_set_stock(self, product: str, value: float) -> None:
        """Set the stock of a product."""
        self.chem.set_stock(product, value)
        self._schedule_save()
        await self.async_update()

    async def async_new_season(self) -> None:
        """Reset season consumption."""
        self.chem.reset_season()
        self._schedule_save()
        await self.async_update()

    async def async_maintenance_done(self, task: str) -> None:
        """Mark a maintenance task as done."""
        self.season.done(task, dt_util.now().date())
        if task == TASK_PROBE:
            self.chem.probe_calibrated()
        self._due_tasks.discard(task)
        self._schedule_save()
        await self.async_update()

    # -------------------------------------------------------------- programs

    async def async_start_program(self, name: str, hours: float | None = None) -> None:
        """Start a special program (PROGRAM_NONE cancels)."""
        now = dt_util.now()
        if hours is None:
            hours = self.boost_hours if name == PROGRAM_BOOST else PROGRAM_HOURS.get(name, 0.0)
        try:
            self.program.start(name, now, hours)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        if self.program.active:
            if name == PROGRAM_NEW_FILL:
                # The whole pool is fresh (iron-rich) water.
                self.fresh_water_l = float(self.config[CONF_VOLUME]) * 1000
            self._fire(EVENT_PROGRAM_STARTED, program=name, hours=hours)
        self._schedule_save()
        await self.async_update()

    async def async_set_boost_hours(self, value: float) -> None:
        """Set the boost duration."""
        self.boost_hours = value
        self._schedule_save()
        await self.async_update()

    # ------------------------------------------------------------------ todo

    def add_todo(self, summary: str, description: str | None = None) -> bool:
        """Add an open task unless an open one with the same text exists."""
        if any(
            item["summary"] == summary and item["status"] == "needs_action"
            for item in self.todo_items
        ):
            return False
        self.todo_items.append(
            {
                "uid": uuid.uuid4().hex,
                "summary": summary,
                "status": "needs_action",
                "description": description,
            }
        )
        self._schedule_save()
        return True

    async def async_todo_changed(self) -> None:
        """Persist todo changes made through the todo entity."""
        self._schedule_save()
        self._notify()

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
            self._integrate_energy(now)
            self._accumulate(now)
            self._read_pump(now)
            await self._async_refresh_forecast(now)
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
        self.week.runtime_s += before + after

    def _read_pump(self, now: datetime) -> None:
        entity_id = self._entity(CONF_PUMP_ENTITY)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state not in (STATE_ON, STATE_OFF):
            pump_on = None
        else:
            pump_on = state.state == STATE_ON
        raw = state.state if state is not None else None
        if self._outage_date != now.date():
            self._outage_date = now.date()
            self.outages_today = 0
        if pump_on is None and self._pump_state_raw in (STATE_ON, STATE_OFF):
            self.outages_today += 1
            self.week.outages += 1
        self._pump_state_raw = raw
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
        data.surface = round(surface_area(volume, float(cfg[CONF_SURFACE])), 2)
        self._refresh_rain(now)
        self._refresh_program(now)
        self._refresh_metal_ex(now)
        data.last_measurement = self._last_measurement()
        self._refresh_visual()
        self._refresh_probe(now)
        forecast = data.forecast
        data.weather_extra_hours = weather_extra_hours(
            heavy_rain=data.heavy_rain,
            max_temp=forecast.max_temp if forecast else None,
            uv_max=forecast.uv_max if forecast else None,
        )
        data.weather_hint = weather_hint(
            rain_last_24h=data.rain_last_24h or 0.0,
            heavy_rain=data.heavy_rain,
            forecast=forecast,
            surface_m2=data.surface,
            language=self.hass.config.language,
        )
        data.recommended_runtime = recommended_runtime(
            data.water_temp,
            extra_hours=data.weather_extra_hours,
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
            GuidanceInputs(
                ph=data.ph,
                orp=data.orp,
                volume_m3=volume,
                ph_minus_g=data.ph_minus_dose,
                ph_plus_g=data.ph_plus_dose,
                chlorine_g=data.chlorine_dose,
                metal_ex_pending_ml=data.metal_ex_dose,
                metal_ex_hours_left=data.metal_ex_hours_left,
                metal_ex_backwash=self.metal_ex_backwash,
                metal_ex_pool_ml=data.metal_ex_pool_dose,
                after_shock=self._after_shock(data.last_measurement),
                visual=tuple(data.visual),
                probe_suspect=data.probe_suspect,
                language=self.hass.config.language,
            )
        )

        # Backwash
        data.backwash_hours = round(self._backwash_s / 3600, 2)
        hours_limit = float(cfg[CONF_BACKWASH_HOURS])
        days_limit = float(cfg[CONF_BACKWASH_DAYS])
        due = hours_limit > 0 and data.backwash_hours >= hours_limit
        if self.last_backwash is not None and days_limit > 0:
            due = due or now - self.last_backwash >= timedelta(days=days_limit)
        data.backwash_due = due or self.metal_ex_backwash

        # Measurement age
        stale_hours = float(cfg[CONF_STALE_HOURS])
        data.measurement_stale = bool(
            stale_hours > 0
            and data.last_measurement is not None
            and now - data.last_measurement > timedelta(hours=stale_hours)
        )

        data.frost_risk = data.air_temp is not None and data.air_temp <= float(cfg[CONF_FROST_TEMP])

        self._refresh_energy(now)
        self._refresh_solar(now)
        self._refresh_stock()
        self._refresh_season(now)
        self._refresh_connection(now)
        self._refresh_motion(now)
        self._refresh_stats(now)

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

    async def _async_refresh_forecast(self, now: datetime) -> None:
        """Fetch the weather forecast every 30 minutes (hourly, else daily)."""
        entity_id = self._entity(CONF_WEATHER_ENTITY)
        if entity_id is None:
            self.data.forecast = None
            return
        fetched = self._forecast_fetched
        if fetched is not None and (now - fetched).total_seconds() < WEATHER_REFRESH_SECONDS:
            self.data.forecast = self._forecast
            return
        self._forecast_fetched = now
        for kind in ("hourly", "daily"):
            try:
                response = await self.hass.services.async_call(
                    "weather",
                    "get_forecasts",
                    {ATTR_ENTITY_ID: entity_id, "type": kind},
                    blocking=True,
                    return_response=True,
                )
            except HomeAssistantError:
                continue
            items = (response or {}).get(entity_id, {}).get("forecast") or []
            if items:
                self._forecast = summarize_forecast(items, now, hourly=kind == "hourly")
                break
        else:
            _LOGGER.debug("%s: no forecast from %s", self.name, entity_id)
        self.data.forecast = self._forecast

    def _refresh_rain(self, now: datetime) -> None:
        """Track rain per hour from a rain gauge or, without one, the forecast."""
        data = self.data
        hour = now.replace(minute=0, second=0, microsecond=0)
        key = hour.isoformat()
        gauge = self._entity(CONF_RAIN_ENTITY)
        if gauge:
            value = self._state_float(CONF_RAIN_ENTITY)
            if value is not None:
                last = self._rain_last_value
                if last is not None:
                    # Daily totals reset to 0; then the new value is the delta.
                    delta = value - last if value >= last else value
                    self._rain_hours[key] = self._rain_hours.get(key, 0.0) + delta
                self._rain_last_value = value
        elif self._forecast is not None and self._forecast.current_hour_rain_mm is not None:
            self._rain_hours[key] = self._forecast.current_hour_rain_mm

        cutoff = hour - timedelta(hours=24)
        self._rain_hours = {
            k: v
            for k, v in self._rain_hours.items()
            if (when := dt_util.parse_datetime(k)) is not None and when > cutoff
        }
        if not gauge and self._forecast is None and not self._rain_hours:
            data.rain_last_24h = None
            data.heavy_rain = False
            return
        total = sum(self._rain_hours.values())
        data.rain_last_24h = round(total, 1)
        threshold = float(self.config[CONF_HEAVY_RAIN])
        heavy = threshold > 0 and total >= threshold
        if heavy and not data.heavy_rain and self._initialized:
            self._fire(EVENT_HEAVY_RAIN, rain_mm=data.rain_last_24h)
        data.heavy_rain = heavy

    def _refresh_program(self, now: datetime) -> None:
        ended = self.program.tick(now)
        if ended:
            follow_up = PROGRAM_FOLLOW_UP.get(ended)
            if follow_up == FOLLOW_UP_MEASURE:
                self.shock_done_at = now
            elif follow_up == FOLLOW_UP_BACKWASH:
                self.metal_ex_backwash = True
            self._fire(EVENT_PROGRAM_DONE, program=ended, follow_up=follow_up)
        self.data.program_hours_left = round(self.program.remaining_hours(now), 1)

    def _after_shock(self, last_measurement: datetime | None) -> bool:
        if self.shock_done_at is None:
            return False
        if last_measurement is not None and last_measurement > self.shock_done_at:
            self.shock_done_at = None
            return False
        return True

    def _refresh_visual(self) -> None:
        entity_id = self._entity(CONF_VISUAL_ENTITY)
        state = self.hass.states.get(entity_id) if entity_id else None
        text = state.state if state is not None else None
        findings = parse_visual(text)
        new = set(findings) - self._visual
        if new and self._initialized:
            self._fire(EVENT_VISUAL_FINDING, findings=sorted(new), text=text)
        self._visual = set(findings)
        self.data.visual = findings
        self.data.visual_text = text

    def _refresh_probe(self, now: datetime) -> None:
        was = self.chem.probe_suspect
        result = self.chem.evaluate_probe(now, self.data.orp, self.data.last_measurement)
        self.data.probe_suspect = self.chem.probe_suspect
        if result is not None and self.chem.probe_suspect and not was:
            self._fire(EVENT_PROBE_CHECK, rise_mv=round(result.rise_mv, 1))
            self.add_todo(checklist(TASK_PROBE, self.hass.config.language)[0])

    def _stock_thresholds(self) -> dict[str, float]:
        cfg = self.config
        return low_stock_thresholds(
            volume_m3=float(cfg[CONF_VOLUME]),
            chlorine_strength=float(cfg[CONF_CHLORINE_STRENGTH]),
            metal_ex_pool_ml=self.data.metal_ex_pool_dose,
        )

    def _refresh_stock(self) -> None:
        thresholds = self._stock_thresholds()
        self.data.low_stock = self.chem.low_products(thresholds)
        new = self.chem.products_to_shop(thresholds)
        if not new or not self._initialized:
            return
        language = self.hass.config.language
        shopping = self._entity(CONF_SHOPPING_LIST_ENTITY)
        for product in new:
            name = product_name(product, language)
            self._fire(EVENT_STOCK_LOW, product=product, stock=self.chem.stock.get(product))
            if shopping:
                self.hass.async_create_task(
                    self._async_add_shopping_item(shopping, f"Pool: {name}")
                )

    async def _async_add_shopping_item(self, entity_id: str, item: str) -> None:
        try:
            await self.hass.services.async_call(
                "todo", "add_item", {ATTR_ENTITY_ID: entity_id, "item": item}, blocking=True
            )
        except HomeAssistantError as err:
            _LOGGER.warning("%s: could not add %s to %s: %s", self.name, item, entity_id, err)

    def maintenance_intervals(self) -> dict[str, float]:
        cfg = self.config
        return {
            TASK_SAND: float(cfg[CONF_SAND_DAYS]),
            TASK_PROBE: float(cfg[CONF_PROBE_DAYS]),
            TASK_SEALS: float(cfg[CONF_SEALS_DAYS]),
        }

    def _refresh_season(self, now: datetime) -> None:
        data = self.data
        today = now.date()
        language = self.hass.config.language
        temp = data.water_temp if data.water_temp is not None else data.air_temp
        self.season.add_temperature(today, temp)
        self.season.ensure_started(today)

        status = self.season.status(today, winter_mode=self.mode == MODE_WINTER)
        previous = self._season_status or SEASON_SWIM
        if status != previous and status in (SEASON_WINTERIZE, SEASON_START):
            self._fire(EVENT_SEASON, season=status)
            for item in checklist(status, language):
                self.add_todo(item)
        self._season_status = status
        data.season = status

        due = self.season.due_tasks(today, self.maintenance_intervals())
        for task in set(due) - self._due_tasks:
            self._fire(EVENT_MAINTENANCE_DUE, task=task)
            for item in checklist(task, language):
                self.add_todo(item)
        self._due_tasks = set(due)
        data.maintenance_due = due

    def _refresh_connection(self, now: datetime) -> None:
        data = self.data
        data.outages_today = self.outages_today
        limit = float(self.config[CONF_OUTAGE_LIMIT])
        unstable = limit > 0 and self.outages_today >= limit
        issue_id = f"pump_unstable_{self.entry.entry_id}"
        if unstable and not data.connection_unstable:
            wifi = self._state_float(CONF_PUMP_WIFI_ENTITY)
            self._fire(EVENT_CONNECTION_UNSTABLE, outages=self.outages_today, wifi=wifi)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="pump_unstable",
                translation_placeholders={
                    "name": self.name,
                    "count": str(self.outages_today),
                    "wifi": f"{wifi:.0f} dBm" if wifi is not None else "–",
                },
            )
        elif not unstable:
            # Also clears an issue left over from before a restart.
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        data.connection_unstable = unstable

    def _refresh_motion(self, now: datetime) -> None:
        motion_id = self._entity(CONF_MOTION_ENTITY)
        presence_id = self._entity(CONF_PRESENCE_ENTITY)
        if not motion_id or not presence_id:
            self.data.motion_away = False
            return
        motion = self.hass.states.get(motion_id)
        presence = self.hass.states.get(presence_id)
        away = presence is not None and presence.state not in ("home", STATE_ON)
        active = motion is not None and motion.state == STATE_ON and away
        if active and not self.data.motion_away:
            last = self._motion_fired
            if last is None or (now - last).total_seconds() >= MOTION_COOLDOWN_SECONDS:
                self._motion_fired = now
                self._fire(EVENT_MOTION_WHILE_AWAY, motion_entity=motion_id)
        self.data.motion_away = active

    def _integrate_energy(self, now: datetime) -> None:
        """Integrate pump power (total and solar share) since the last update."""
        last, self._last_energy_tick = self._last_energy_tick, now
        if self._energy_counter_date != now.date():
            self._energy_counter_date = now.date()
            self.energy_today_counter = EnergyCounter()
        if last is None or not self._pump_on:
            return
        seconds = min((now - last).total_seconds(), 2 * TICK_SECONDS)
        pump_w = self.data.pump_power
        solar_w = self._state_float(CONF_SOLAR_POWER_ENTITY)
        self.energy_today_counter.add(seconds, pump_w, solar_w)
        self.week.energy.add(seconds, pump_w, solar_w)

    def _refresh_stats(self, now: datetime) -> None:
        data = self.data
        price = self.electricity_price
        counter = self.energy_today_counter
        data.power_energy_today = round(counter.energy_kwh, 3)
        data.solar_energy_today = round(counter.solar_kwh, 3)
        data.solar_share_today = counter.solar_share
        data.solar_savings_today = round(counter.solar_kwh * price, 2)
        data.solar_savings_rate = (
            solar_savings_rate(data.pump_power, self._state_float(CONF_SOLAR_POWER_ENTITY), price)
            if self._pump_on
            else 0.0
        )

        forecast = data.forecast
        air = forecast.max_temp if forecast and forecast.max_temp is not None else data.air_temp
        data.swim_score = swim_score(
            water_temp=data.water_temp,
            air_temp=air,
            rain_mm=forecast.rain_mm if forecast else None,
            thunder=forecast.thunder if forecast else False,
            quality=data.quality,
        )
        data.swim_label = swim_label(data.swim_score)

        week = self.week
        if week.start is None:
            week.start = now.date()
        week.ph.add(data.ph)
        week.orp.add(data.orp)
        week.water_temp.add(data.water_temp)
        if report_due(now, self.last_report_date):
            since = datetime.combine(week.start, time.min, tzinfo=now.tzinfo)
            text, details = build_report(
                week,
                doses=self.chem.doses_since(since),
                price=price,
                language=self.hass.config.language,
                now=now,
            )
            self.last_report_date = now.date()
            self.last_report_text = text
            self.last_report_details = details
            self._fire(EVENT_WEEKLY_REPORT, text=text, **details)
            self.week = WeekStats(start=now.date())

    def _refresh_metal_ex(self, now: datetime) -> None:
        data = self.data
        cfg = self.config
        volume = float(cfg[CONF_VOLUME])
        if self.metal_ex_until is not None and now >= self.metal_ex_until:
            self.metal_ex_until = None
            self.metal_ex_backwash = True
            self._fire(EVENT_METAL_EX_DONE)
        remaining = (
            (self.metal_ex_until - now).total_seconds() / 3600 if self.metal_ex_until else 0.0
        )
        data.metal_ex_hours_left = round(max(0.0, remaining), 1)
        data.fresh_water_l = round(self.fresh_water_l)
        data.metal_ex_dose = metal_ex_dose(self.fresh_water_l, float(cfg[CONF_METAL_EX_FRESH]))
        data.metal_ex_pool_dose = metal_ex_dose(volume * 1000, float(cfg[CONF_METAL_EX_POOL]))
        data.metal_ex_problem_dose = metal_ex_dose(
            volume * 1000, 2 * float(cfg[CONF_METAL_EX_POOL])
        )

    def _last_measurement(self) -> datetime | None:
        if entity_id := self._entity(CONF_LAST_MEASUREMENT_ENTITY):
            state = self.hass.states.get(entity_id)
            if state is not None and (parsed := dt_util.parse_datetime(state.state)):
                return dt_util.as_local(parsed)
            return None
        # Without a timestamp entity: the newest report of the pH or redox sensor.
        reported = [
            state.last_reported
            for key in (CONF_PH_ENTITY, CONF_ORP_ENTITY)
            if (entity_id := self._entity(key))
            and (state := self.hass.states.get(entity_id)) is not None
        ]
        return dt_util.as_local(max(reported)) if reported else None

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
                metal_ex_active=self.data.metal_ex_hours_left > 0,
                program_active=self.program.active,
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
            "solar_savings": own("sensor", "solar_savings_rate"),
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
