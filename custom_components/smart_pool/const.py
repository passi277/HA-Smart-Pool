"""Constants for the Smart Pool integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "smart_pool"
EVENT_SMART_POOL: Final = "smart_pool_event"

# --- Config entry data (required core setup) -------------------------------
CONF_VOLUME: Final = "volume"
CONF_PH_ENTITY: Final = "ph_entity"
CONF_ORP_ENTITY: Final = "orp_entity"
CONF_WATER_TEMP_ENTITY: Final = "water_temp_entity"
CONF_PUMP_ENTITY: Final = "pump_entity"

# --- Optional source entities ----------------------------------------------
CONF_PUMP_POWER_ENTITY: Final = "pump_power_entity"
CONF_PUMP_ENERGY_ENTITY: Final = "pump_energy_entity"
CONF_SOLAR_POWER_ENTITY: Final = "solar_power_entity"
CONF_BATTERY_SOC_ENTITY: Final = "battery_soc_entity"
CONF_AIR_TEMP_ENTITY: Final = "air_temp_entity"
CONF_LAST_MEASUREMENT_ENTITY: Final = "last_measurement_entity"

OPTIONAL_ENTITY_KEYS: Final = (
    CONF_PUMP_POWER_ENTITY,
    CONF_PUMP_ENERGY_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_AIR_TEMP_ENTITY,
    CONF_LAST_MEASUREMENT_ENTITY,
)

# --- Tunable parameters (options) ------------------------------------------
CONF_PUMP_FLOW: Final = "pump_flow"
CONF_MIN_RUNTIME: Final = "min_runtime"
CONF_MAX_RUNTIME: Final = "max_runtime"
CONF_CHLORINE_STRENGTH: Final = "chlorine_strength"
CONF_CHLORINE_STEP: Final = "chlorine_step"
CONF_DRY_RUN_POWER: Final = "dry_run_power"
CONF_BACKWASH_HOURS: Final = "backwash_hours"
CONF_BACKWASH_DAYS: Final = "backwash_days"
CONF_SOLAR_THRESHOLD: Final = "solar_threshold"
CONF_BATTERY_MIN_SOC: Final = "battery_min_soc"
CONF_CATCHUP_TIME: Final = "catchup_time"
CONF_FROST_TEMP: Final = "frost_temp"
CONF_STALE_HOURS: Final = "stale_hours"

DEFAULTS: Final[dict[str, float | str]] = {
    CONF_VOLUME: 30.0,
    CONF_PUMP_FLOW: 0.0,
    CONF_MIN_RUNTIME: 2.0,
    CONF_MAX_RUNTIME: 12.0,
    CONF_CHLORINE_STRENGTH: 56.0,
    CONF_CHLORINE_STEP: 1.0,
    CONF_DRY_RUN_POWER: 0.0,
    CONF_BACKWASH_HOURS: 50.0,
    CONF_BACKWASH_DAYS: 14.0,
    CONF_SOLAR_THRESHOLD: 400.0,
    CONF_BATTERY_MIN_SOC: 0.0,
    CONF_CATCHUP_TIME: "17:00:00",
    CONF_FROST_TEMP: 2.0,
    CONF_STALE_HOURS: 12.0,
}

# --- Operating modes -------------------------------------------------------
MODE_MANUAL: Final = "manual"
MODE_OFF: Final = "off"
MODE_AUTO: Final = "auto"
MODE_SOLAR: Final = "solar"
MODE_CONTINUOUS: Final = "continuous"
MODE_WINTER: Final = "winter"

MODES: Final = (
    MODE_MANUAL,
    MODE_OFF,
    MODE_AUTO,
    MODE_SOLAR,
    MODE_CONTINUOUS,
    MODE_WINTER,
)

DEFAULT_MODE: Final = MODE_MANUAL
DEFAULT_START_TIME: Final = "10:00:00"

# --- Water quality ---------------------------------------------------------
QUALITY_OK: Final = "ok"
QUALITY_CHECK: Final = "check"
QUALITY_CRITICAL: Final = "critical"
QUALITY_UNKNOWN: Final = "unknown"
QUALITY_STATES: Final = (QUALITY_OK, QUALITY_CHECK, QUALITY_CRITICAL, QUALITY_UNKNOWN)

# (critical_low, ok_low, ok_high, critical_high)
PH_RANGES: Final = (6.8, 7.2, 7.6, 8.0)
ORP_RANGES: Final = (400.0, 650.0, 800.0, 900.0)
PH_TARGET: Final = 7.4

# Rule of thumb from product labels: ~10 g per m³ shifts pH by 0.1.
PH_MINUS_G_PER_M3_PER_STEP: Final = 10.0
PH_PLUS_G_PER_M3_PER_STEP: Final = 10.0

# --- Controller timing -----------------------------------------------------
TICK_SECONDS: Final = 30
SOLAR_CONFIRM_SECONDS: Final = 600
MIN_SWITCH_INTERVAL_SECONDS: Final = 120
DRY_RUN_GRACE_SECONDS: Final = 60
DRY_RUN_CONFIRM_SECONDS: Final = 120
FROST_RUN_MINUTES: Final = 15

# --- Controller status -----------------------------------------------------
STATUS_MANUAL: Final = "manual"
STATUS_OFF: Final = "off"
STATUS_FAULT: Final = "fault"
STATUS_PUMP_UNAVAILABLE: Final = "pump_unavailable"
STATUS_TARGET_REACHED: Final = "target_reached"
STATUS_WAITING_SCHEDULE: Final = "waiting_schedule"
STATUS_RUNNING_SCHEDULE: Final = "running_schedule"
STATUS_WAITING_SUN: Final = "waiting_sun"
STATUS_RUNNING_SOLAR: Final = "running_solar"
STATUS_RUNNING_CATCHUP: Final = "running_catchup"
STATUS_RUNNING_CONTINUOUS: Final = "running_continuous"
STATUS_FROST_PROTECTION: Final = "frost_protection"
STATUS_WINTER_IDLE: Final = "winter_idle"
STATUS_NO_AIR_TEMP: Final = "no_air_temp"

STATUSES: Final = (
    STATUS_MANUAL,
    STATUS_OFF,
    STATUS_FAULT,
    STATUS_PUMP_UNAVAILABLE,
    STATUS_TARGET_REACHED,
    STATUS_WAITING_SCHEDULE,
    STATUS_RUNNING_SCHEDULE,
    STATUS_WAITING_SUN,
    STATUS_RUNNING_SOLAR,
    STATUS_RUNNING_CATCHUP,
    STATUS_RUNNING_CONTINUOUS,
    STATUS_FROST_PROTECTION,
    STATUS_WINTER_IDLE,
    STATUS_NO_AIR_TEMP,
)

# --- Event types fired on the bus -----------------------------------------
EVENT_WATER_QUALITY_CHANGED: Final = "water_quality_changed"
EVENT_MEASUREMENT_STALE: Final = "measurement_stale"
EVENT_BACKWASH_DUE: Final = "backwash_due"
EVENT_BACKWASH_DONE: Final = "backwash_done"
EVENT_PUMP_FAULT: Final = "pump_fault"
EVENT_PUMP_STARTED: Final = "pump_started"
EVENT_PUMP_STOPPED: Final = "pump_stopped"
