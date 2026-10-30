"""Knopf: Lernfaktor zurücksetzen."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import AcPidFrequencyController
from .entity import AcPidFrequencyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ResetLearningButton(entry.runtime_data)])


class ResetLearningButton(AcPidFrequencyEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:restore"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "reset_learning")

    async def async_press(self) -> None:
        self.controller.async_reset_learning()
