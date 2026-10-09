"""Services for Smart Pool."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .chemistry import PRODUCTS
from .const import (
    ATTR_AMOUNT,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_HOURS,
    ATTR_PRODUCT,
    ATTR_PROGRAM,
    DOMAIN,
    SERVICE_LOG_DOSE,
    SERVICE_START_PROGRAM,
)
from .controller import SmartPoolController
from .programs import PROGRAMS

LOG_DOSE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PRODUCT): vol.In(PRODUCTS),
        vol.Optional(ATTR_AMOUNT): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)
START_PROGRAM_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PROGRAM): vol.In(PROGRAMS),
        vol.Optional(ATTR_HOURS): vol.All(vol.Coerce(float), vol.Range(min=0, max=336)),
    }
)


def _controller(hass: HomeAssistant, call: ServiceCall) -> SmartPoolController:
    entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
    return entry.runtime_data


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration services."""

    async def log_dose(call: ServiceCall) -> None:
        await _controller(hass, call).async_log_dose(
            call.data[ATTR_PRODUCT], call.data.get(ATTR_AMOUNT)
        )

    async def start_program(call: ServiceCall) -> None:
        await _controller(hass, call).async_start_program(
            call.data[ATTR_PROGRAM], call.data.get(ATTR_HOURS)
        )

    hass.services.async_register(DOMAIN, SERVICE_LOG_DOSE, log_dose, schema=LOG_DOSE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_START_PROGRAM, start_program, schema=START_PROGRAM_SCHEMA
    )
