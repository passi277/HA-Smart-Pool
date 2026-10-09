"""Select entities for Smart Pool."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SmartPoolConfigEntry
from .chemistry import PRODUCTS
from .const import MODES
from .controller import SmartPoolController
from .entity import SmartPoolEntity
from .programs import PROGRAM_NONE, PROGRAMS


@dataclass(frozen=True, kw_only=True)
class SmartPoolSelectDescription(SelectEntityDescription):
    """Describes a Smart Pool select."""

    value_fn: Callable[[SmartPoolController], str]
    select_fn: Callable[[SmartPoolController, str], Awaitable[None]]


SELECTS: tuple[SmartPoolSelectDescription, ...] = (
    SmartPoolSelectDescription(
        key="mode",
        options=list(MODES),
        value_fn=lambda c: c.mode,
        select_fn=lambda c, o: c.async_set_mode(o),
    ),
    SmartPoolSelectDescription(
        key="program",
        options=list(PROGRAMS),
        value_fn=lambda c: c.program.name if c.program.active else PROGRAM_NONE,
        select_fn=lambda c, o: c.async_start_program(o),
    ),
    SmartPoolSelectDescription(
        key="dose_product",
        options=list(PRODUCTS),
        value_fn=lambda c: c.dose_product,
        select_fn=lambda c, o: c.async_set_dose_product(o),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects."""
    controller = entry.runtime_data
    async_add_entities(SmartPoolSelect(controller, desc) for desc in SELECTS)


class SmartPoolSelect(SmartPoolEntity, SelectEntity):
    """Mode, program or dose product."""

    entity_description: SmartPoolSelectDescription

    def __init__(
        self, controller: SmartPoolController, description: SmartPoolSelectDescription
    ) -> None:
        """Initialize the select."""
        super().__init__(controller, description.key)
        self.entity_description = description

    @property
    def current_option(self) -> str:
        """Return the current option."""
        return self.entity_description.value_fn(self.controller)

    async def async_select_option(self, option: str) -> None:
        """Change the option."""
        await self.entity_description.select_fn(self.controller, option)
