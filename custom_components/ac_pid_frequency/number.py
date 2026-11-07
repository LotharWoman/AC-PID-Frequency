"""Zahlen-Entität: Ziel-Hz."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfFrequency
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TARGET_HZ_MAX, TARGET_HZ_MIN
from .controller import AcPidFrequencyController
from .entity import AcPidFrequencyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller: AcPidFrequencyController = entry.runtime_data
    async_add_entities([TargetHzNumber(controller)])


class TargetHzNumber(AcPidFrequencyEntity, NumberEntity):
    """Ziel-Frequenz. Hier schreiben auch eigene Automationen (z. B. PV-Logik) hinein."""

    _attr_device_class = NumberDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = TARGET_HZ_MIN
    _attr_native_max_value = TARGET_HZ_MAX
    _attr_icon = "mdi:sine-wave"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "target_hz")

    @property
    def native_value(self) -> float:
        return self.controller.target_hz

    async def async_set_native_value(self, value: float) -> None:
        self.controller.async_set_target_hz(value)
