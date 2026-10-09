"""Buttons for Smart Pool."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SmartPoolConfigEntry
from .controller import SmartPoolController
from .entity import SmartPoolEntity
from .season import TASK_PROBE, TASK_SAND, TASK_SEALS


@dataclass(frozen=True, kw_only=True)
class SmartPoolButtonDescription(ButtonEntityDescription):
    """Describes a Smart Pool button."""

    press_fn: Callable[[SmartPoolController], Awaitable[None]]


BUTTONS: tuple[SmartPoolButtonDescription, ...] = (
    SmartPoolButtonDescription(
        key="backwash_done",
        press_fn=lambda c: c.async_backwash_done(),
    ),
    SmartPoolButtonDescription(
        key="refilled",
        press_fn=lambda c: c.async_refilled(),
    ),
    SmartPoolButtonDescription(
        key="metal_ex_added",
        press_fn=lambda c: c.async_metal_ex_added(),
    ),
    SmartPoolButtonDescription(
        key="log_dose",
        press_fn=lambda c: c.async_log_selected_dose(),
    ),
    SmartPoolButtonDescription(
        key="new_season",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_new_season(),
    ),
    SmartPoolButtonDescription(
        key="sand_changed",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_maintenance_done(TASK_SAND),
    ),
    SmartPoolButtonDescription(
        key="probe_calibrated",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_maintenance_done(TASK_PROBE),
    ),
    SmartPoolButtonDescription(
        key="seals_checked",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_maintenance_done(TASK_SEALS),
    ),
    SmartPoolButtonDescription(
        key="reset_fault",
        press_fn=lambda c: c.async_reset_fault(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Smart Pool buttons."""
    controller = entry.runtime_data
    async_add_entities(SmartPoolButton(controller, desc) for desc in BUTTONS)


class SmartPoolButton(SmartPoolEntity, ButtonEntity):
    """A pool action."""

    entity_description: SmartPoolButtonDescription

    def __init__(
        self, controller: SmartPoolController, description: SmartPoolButtonDescription
    ) -> None:
        """Initialize the button."""
        super().__init__(controller, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Handle the press."""
        await self.entity_description.press_fn(self.controller)
