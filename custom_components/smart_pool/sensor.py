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
    UnitOfEnergy,
    UnitOfMass,
    UnitOfPrecipitationDepth,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SmartPoolConfigEntry
from .const import CONF_BACKWASH_HOURS, QUALITY_STATES, STATUSES
from .controller import SmartPoolController
from .entity import SmartPoolEntity


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
        """Return the sensor value."""
        return self.entity_description.value_fn(self.controller)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.controller)
