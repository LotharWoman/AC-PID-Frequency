"""Knöpfe: Lernfaktor und Mindestmodulation zurücksetzen."""

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
    controller: AcPidFrequencyController = entry.runtime_data
    async_add_entities(
        [
            ResetLearningButton(controller),
            ResetMinHzButton(controller),
        ]
    )


class ResetLearningButton(AcPidFrequencyEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:restore"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "reset_learning")

    async def async_press(self) -> None:
        self.controller.async_reset_learning()


class ResetMinHzButton(AcPidFrequencyEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:arrow-collapse-down"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "reset_min_hz")

    async def async_press(self) -> None:
        self.controller.async_reset_min_hz()
