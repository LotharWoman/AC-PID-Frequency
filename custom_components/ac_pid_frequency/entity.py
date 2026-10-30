"""Gemeinsame Basisklasse der Entitäten."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .controller import AcPidFrequencyController


class AcPidFrequencyEntity(Entity):
    """Entität, die sich bei jedem Reglertakt aktualisiert."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: AcPidFrequencyController, key: str) -> None:
        self.controller = controller
        self._key = key
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = controller.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self.controller.signal, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
