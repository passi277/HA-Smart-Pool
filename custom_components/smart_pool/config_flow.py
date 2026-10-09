"""Config flow for Smart Pool."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

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
    CONF_ORP_ENTITY,
    CONF_PH_ENTITY,
    CONF_PUMP_ENERGY_ENTITY,
    CONF_PUMP_ENTITY,
    CONF_PUMP_FLOW,
    CONF_PUMP_POWER_ENTITY,
    CONF_RAIN_ENTITY,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLAR_THRESHOLD,
    CONF_STALE_HOURS,
    CONF_SURFACE,
    CONF_VOLUME,
    CONF_WATER_TEMP_ENTITY,
    CONF_WEATHER_ENTITY,
    DEFAULTS,
    DOMAIN,
    OPTIONAL_ENTITY_KEYS,
)

PUMP_DOMAINS = ["switch", "input_boolean"]


def _sensor(device_class: SensorDeviceClass | None = None) -> selector.EntitySelector:
    config = selector.EntitySelectorConfig(domain="sensor")
    if device_class is not None:
        config = selector.EntitySelectorConfig(domain="sensor", device_class=device_class)
    return selector.EntitySelector(config)


def _number(
    minimum: float, maximum: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _core_schema(defaults: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Pool"))] = (
            selector.TextSelector()
        )
    fields.update(
        {
            vol.Required(
                CONF_VOLUME, default=defaults.get(CONF_VOLUME, DEFAULTS[CONF_VOLUME])
            ): _number(1, 500, 0.5, "m³"),
            vol.Required(
                CONF_PH_ENTITY, default=defaults.get(CONF_PH_ENTITY, vol.UNDEFINED)
            ): _sensor(),
            vol.Required(
                CONF_ORP_ENTITY, default=defaults.get(CONF_ORP_ENTITY, vol.UNDEFINED)
            ): _sensor(),
            vol.Required(
                CONF_WATER_TEMP_ENTITY,
                default=defaults.get(CONF_WATER_TEMP_ENTITY, vol.UNDEFINED),
            ): _sensor(SensorDeviceClass.TEMPERATURE),
            vol.Required(
                CONF_PUMP_ENTITY, default=defaults.get(CONF_PUMP_ENTITY, vol.UNDEFINED)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain=PUMP_DOMAINS)),
        }
    )
    return vol.Schema(fields)


def _optional_entities_schema(values: dict[str, Any]) -> dict[Any, Any]:
    selectors = {
        CONF_PUMP_POWER_ENTITY: _sensor(SensorDeviceClass.POWER),
        CONF_PUMP_ENERGY_ENTITY: _sensor(SensorDeviceClass.ENERGY),
        CONF_SOLAR_POWER_ENTITY: _sensor(SensorDeviceClass.POWER),
        CONF_BATTERY_SOC_ENTITY: _sensor(SensorDeviceClass.BATTERY),
        CONF_AIR_TEMP_ENTITY: _sensor(SensorDeviceClass.TEMPERATURE),
        CONF_LAST_MEASUREMENT_ENTITY: _sensor(SensorDeviceClass.TIMESTAMP),
        CONF_WEATHER_ENTITY: selector.EntitySelector(
            selector.EntitySelectorConfig(domain="weather")
        ),
        CONF_RAIN_ENTITY: _sensor(SensorDeviceClass.PRECIPITATION),
    }
    return {
        vol.Optional(key, description={"suggested_value": values.get(key)}): sel
        for key, sel in selectors.items()
    }


def _parameters_schema(values: dict[str, Any]) -> dict[Any, Any]:
    def default(key: str) -> Any:
        return values.get(key, DEFAULTS[key])

    return {
        vol.Required(CONF_SURFACE, default=default(CONF_SURFACE)): _number(0, 500, 0.1, "m²"),
        vol.Required(CONF_PUMP_FLOW, default=default(CONF_PUMP_FLOW)): _number(0, 100, 0.5, "m³/h"),
        vol.Required(CONF_MIN_RUNTIME, default=default(CONF_MIN_RUNTIME)): _number(0, 24, 0.5, "h"),
        vol.Required(CONF_MAX_RUNTIME, default=default(CONF_MAX_RUNTIME)): _number(0, 24, 0.5, "h"),
        vol.Required(CONF_CHLORINE_STRENGTH, default=default(CONF_CHLORINE_STRENGTH)): _number(
            1, 100, 1, "%"
        ),
        vol.Required(CONF_CHLORINE_STEP, default=default(CONF_CHLORINE_STEP)): _number(
            0.1, 10, 0.1, "mg/l"
        ),
        vol.Required(CONF_DRY_RUN_POWER, default=default(CONF_DRY_RUN_POWER)): _number(
            0, 5000, 5, "W"
        ),
        vol.Required(CONF_BACKWASH_HOURS, default=default(CONF_BACKWASH_HOURS)): _number(
            0, 1000, 1, "h"
        ),
        vol.Required(CONF_BACKWASH_DAYS, default=default(CONF_BACKWASH_DAYS)): _number(
            0, 365, 1, "d"
        ),
        vol.Required(CONF_SOLAR_THRESHOLD, default=default(CONF_SOLAR_THRESHOLD)): _number(
            0, 20000, 10, "W"
        ),
        vol.Required(CONF_BATTERY_MIN_SOC, default=default(CONF_BATTERY_MIN_SOC)): _number(
            0, 100, 1, "%"
        ),
        vol.Required(
            CONF_CATCHUP_TIME, default=default(CONF_CATCHUP_TIME)
        ): selector.TimeSelector(),
        vol.Required(CONF_FROST_TEMP, default=default(CONF_FROST_TEMP)): _number(
            -20, 10, 0.5, "°C"
        ),
        vol.Required(CONF_STALE_HOURS, default=default(CONF_STALE_HOURS)): _number(0, 168, 1, "h"),
        vol.Required(CONF_HEAVY_RAIN, default=default(CONF_HEAVY_RAIN)): _number(0, 200, 1, "mm"),
        vol.Required(CONF_METAL_EX_FRESH, default=default(CONF_METAL_EX_FRESH)): _number(
            0, 500, 5, "ml/m³"
        ),
        vol.Required(CONF_METAL_EX_POOL, default=default(CONF_METAL_EX_POOL)): _number(
            0, 500, 5, "ml/m³"
        ),
        vol.Required(CONF_METAL_EX_HOURS, default=default(CONF_METAL_EX_HOURS)): _number(
            0, 168, 1, "h"
        ),
    }


class SmartPoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: name, volume and the required entities."""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_PUMP_ENTITY])
            self._abort_if_unique_id_configured()
            self._data = user_input
            return await self.async_step_optional()

        return self.async_show_form(step_id="user", data_schema=_core_schema({}, True))

    async def async_step_optional(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: optional entities (power, energy, solar, air temp)."""
        if user_input is not None:
            data = dict(self._data)
            name = data.pop(CONF_NAME)
            options = {k: v for k, v in user_input.items() if v}
            return self.async_create_entry(title=name, data=data, options=options)

        return self.async_show_form(
            step_id="optional", data_schema=vol.Schema(_optional_entities_schema({}))
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SmartPoolOptionsFlow:
        """Return the options flow."""
        return SmartPoolOptionsFlow()


class SmartPoolOptionsFlow(OptionsFlow):
    """Change entities and parameters after setup."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._core: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: core entities and volume."""
        if user_input is not None:
            self._core = user_input
            return await self.async_step_settings()

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_core_schema(current, False))

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: optional entities and tuning parameters."""
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            options = {**self._core, **user_input}
            # Cleared optional selectors are omitted; drop them explicitly.
            for key in OPTIONAL_ENTITY_KEYS:
                if not options.get(key):
                    options.pop(key, None)
            return self.async_create_entry(data=options)

        schema = {**_optional_entities_schema(current), **_parameters_schema(current)}
        return self.async_show_form(step_id="settings", data_schema=vol.Schema(schema))
