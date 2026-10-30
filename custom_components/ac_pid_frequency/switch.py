"""Schalter: Hz-Regelung ein/aus."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import AcPidFrequencyController
from .entity import AcPidFrequencyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([EnabledSwitch(entry.runtime_data)])


class EnabledSwitch(AcPidFrequencyEntity, SwitchEntity):
    """Aus: Fake-Sensor ist unavailable, die Anlage regelt mit ihrem eigenen Sensor."""

    _attr_icon = "mdi:thermostat-auto"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "enabled")

    @property
    def is_on(self) -> bool:
        return self.controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.async_set_enabled(False)
