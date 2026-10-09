"""Sensors for Smart Pool."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfMass,
    UnitOfPrecipitationDepth,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SmartPoolConfigEntry
from .chemistry import PRODUCT_UNITS
from .const import CONF_BACKWASH_HOURS, CONF_METAL_EX_HOURS, QUALITY_STATES, STATUSES
from .controller import SmartPoolController
from .entity import SmartPoolEntity
from .season import MAINTENANCE_TASKS, SEASONS


@dataclass(frozen=True, kw_only=True)
class SmartPoolSensorDescription(SensorEntityDescription):
    """Describes a Smart Pool sensor."""

    value_fn: Callable[[SmartPoolController], Any]
    attrs_fn: Callable[[SmartPoolController], dict[str, Any]] | None = None


def _quality_attrs(c: SmartPoolController) -> dict[str, Any]:
    d = c.data
    return {
        "ph": d.ph,
        "orp": d.orp,
        "water_temperature": d.water_temp,
        "ph_status": d.ph_status,
        "orp_status": d.orp_status,
        "card_entities": c.card_entities(),
    }


def _consumption(product: str, unit: str) -> SmartPoolSensorDescription:
    return SmartPoolSensorDescription(
        key=f"consumption_{product}",
        native_unit_of_measurement=unit,
        suggested_display_precision=0,
        value_fn=lambda c: round(c.chem.consumption.get(product, 0.0)),
        attrs_fn=lambda c: {"stock": c.chem.stock.get(product)},
    )


def _dose_attrs(c: SmartPoolController) -> dict[str, Any]:
    entry = c.chem.last_dose()
    return {
        "product": entry.product if entry else None,
        "amount": entry.amount if entry else None,
        "unit": PRODUCT_UNITS[entry.product] if entry else None,
        "log": [
            {"time": e.time.isoformat(), "product": e.product, "amount": e.amount}
            for e in reversed(c.chem.log[-10:])
        ],
    }


def _forecast_attrs(c: SmartPoolController) -> dict[str, Any]:
    f = c.data.forecast
    if f is None:
        return {}
    return {
        "liters": round(f.rain_mm * c.data.surface),
        "max_temperature": f.max_temp,
        "min_temperature": f.min_temp,
        "uv_index_max": f.uv_max,
        "thunderstorm": f.thunder,
        "extra_runtime_hours": c.data.weather_extra_hours,
    }


MAX_STATE_LENGTH = 255

SENSORS: tuple[SmartPoolSensorDescription, ...] = (
    SmartPoolSensorDescription(
        key="water_quality",
        device_class=SensorDeviceClass.ENUM,
        options=list(QUALITY_STATES),
        value_fn=lambda c: c.data.quality,
        attrs_fn=_quality_attrs,
    ),
    SmartPoolSensorDescription(
        key="guidance",
        value_fn=lambda c: c.data.guidance,
        attrs_fn=lambda c: {"full_text": c.data.guidance},
    ),
    SmartPoolSensorDescription(
        key="ph_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(QUALITY_STATES),
        value_fn=lambda c: c.data.ph_status,
    ),
    SmartPoolSensorDescription(
        key="orp_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(QUALITY_STATES),
        value_fn=lambda c: c.data.orp_status,
    ),
    SmartPoolSensorDescription(
        key="pump_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(STATUSES),
        value_fn=lambda c: c.status,
        attrs_fn=lambda c: {"mode": c.mode, "pump_on": c.pump_on},
    ),
    SmartPoolSensorDescription(
        key="recommended_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda c: c.data.recommended_runtime,
    ),
    SmartPoolSensorDescription(
        key="runtime_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda c: c.data.runtime_today,
    ),
    SmartPoolSensorDescription(
        key="remaining_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=2,
        value_fn=lambda c: c.data.remaining_runtime,
    ),
    SmartPoolSensorDescription(
        key="backwash_hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda c: c.data.backwash_hours,
        attrs_fn=lambda c: {"interval_hours": c.config[CONF_BACKWASH_HOURS]},
    ),
    SmartPoolSensorDescription(
        key="last_backwash",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.last_backwash,
    ),
    SmartPoolSensorDescription(
        key="last_measurement",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.data.last_measurement,
    ),
    SmartPoolSensorDescription(
        key="chlorine_dose",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        suggested_display_precision=0,
        value_fn=lambda c: c.data.chlorine_dose,
    ),
    SmartPoolSensorDescription(
        key="ph_minus_dose",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        suggested_display_precision=0,
        value_fn=lambda c: c.data.ph_minus_dose,
    ),
    SmartPoolSensorDescription(
        key="ph_plus_dose",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        suggested_display_precision=0,
        value_fn=lambda c: c.data.ph_plus_dose,
    ),
    SmartPoolSensorDescription(
        key="weather_hint",
        value_fn=lambda c: c.data.weather_hint,
    ),
    SmartPoolSensorDescription(
        key="rain_last_24h",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        suggested_display_precision=1,
        value_fn=lambda c: c.data.rain_last_24h,
        attrs_fn=lambda c: {
            "liters": round((c.data.rain_last_24h or 0) * c.data.surface),
            "source": "gauge" if c.config.get("rain_entity") else "forecast",
        },
    ),
    SmartPoolSensorDescription(
        key="rain_forecast_24h",
        device_class=SensorDeviceClass.PRECIPITATION,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        suggested_display_precision=1,
        value_fn=lambda c: c.data.forecast.rain_mm if c.data.forecast else None,
        attrs_fn=lambda c: _forecast_attrs(c),
    ),
    SmartPoolSensorDescription(
        key="metal_ex_dose",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        suggested_display_precision=0,
        value_fn=lambda c: c.data.metal_ex_dose,
        attrs_fn=lambda c: {
            "fresh_water_liters": c.data.fresh_water_l,
            "whole_pool_preventive_ml": c.data.metal_ex_pool_dose,
            "whole_pool_discoloured_ml": c.data.metal_ex_problem_dose,
            "refill_cm": c.refill_cm,
            "surface_m2": c.data.surface,
        },
    ),
    SmartPoolSensorDescription(
        key="metal_ex_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda c: c.data.metal_ex_hours_left,
        attrs_fn=lambda c: {"total_hours": c.config[CONF_METAL_EX_HOURS]},
    ),
    SmartPoolSensorDescription(
        key="last_dose",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: e.time if (e := c.chem.last_dose()) else None,
        attrs_fn=lambda c: _dose_attrs(c),
    ),
    *(_consumption(product, unit) for product, unit in PRODUCT_UNITS.items()),
    SmartPoolSensorDescription(
        key="program_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda c: c.data.program_hours_left,
        attrs_fn=lambda c: {"program": c.program.name, "until": c.program.until},
    ),
    SmartPoolSensorDescription(
        key="season",
        device_class=SensorDeviceClass.ENUM,
        options=list(SEASONS),
        value_fn=lambda c: c.data.season,
        attrs_fn=lambda c: {
            f"next_{task}": c.season.next_due(task, c.maintenance_intervals())
            for task in MAINTENANCE_TASKS
        },
    ),
    SmartPoolSensorDescription(
        key="swim_score",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda c: c.data.swim_score,
        attrs_fn=lambda c: {"rating": c.data.swim_label},
    ),
    SmartPoolSensorDescription(
        key="solar_energy_today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda c: c.data.solar_energy_today,
        attrs_fn=lambda c: {"pump_energy_from_power_kwh": c.data.power_energy_today},
    ),
    SmartPoolSensorDescription(
        key="solar_share_today",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda c: c.data.solar_share_today,
    ),
    SmartPoolSensorDescription(
        key="solar_savings_today",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda c: c.data.solar_savings_today,
    ),
    SmartPoolSensorDescription(
        key="solar_savings_rate",
        native_unit_of_measurement="EUR/h",
        suggested_display_precision=2,
        value_fn=lambda c: c.data.solar_savings_rate,
    ),
    SmartPoolSensorDescription(
        key="weekly_report",
        value_fn=lambda c: c.last_report_text,
        attrs_fn=lambda c: {**c.last_report_details, "full_text": c.last_report_text},
    ),
    SmartPoolSensorDescription(
        key="pump_outages_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.data.outages_today,
    ),
    SmartPoolSensorDescription(
        key="energy_today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda c: c.data.energy_today,
    ),
    SmartPoolSensorDescription(
        key="cost_today",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
        value_fn=lambda c: c.data.cost_today,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Smart Pool sensors."""
    controller = entry.runtime_data
    async_add_entities(SmartPoolSensor(controller, desc) for desc in SENSORS)


class SmartPoolSensor(SmartPoolEntity, SensorEntity):
    """A derived pool value."""

    entity_description: SmartPoolSensorDescription

    def __init__(
        self, controller: SmartPoolController, description: SmartPoolSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(controller, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | str | datetime | None:
        """Return the sensor value (texts are cut to the 255 char state limit)."""
        value = self.entity_description.value_fn(self.controller)
        if isinstance(value, str) and len(value) > MAX_STATE_LENGTH:
            return value[: MAX_STATE_LENGTH - 1] + "…"
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.controller)
