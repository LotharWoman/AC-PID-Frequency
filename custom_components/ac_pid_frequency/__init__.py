"""AC PID Frequency: stellt der Klimaanlage einen vorgetäuschten Raumsensor bereit, mit dem sie auf eine Ziel-Frequenz einpendelt."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CARD_FILE, CARD_URL, DOMAIN, PLATFORMS, STORAGE_VERSION
from .controller import AcPidFrequencyController

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Lovelace-Karte ausliefern und automatisch in alle Dashboards laden."""
    integration = await async_get_integration(hass, DOMAIN)
    card = Path(__file__).parent / "frontend" / CARD_FILE
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), False)])
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller = AcPidFrequencyController(hass, entry)
    await controller.async_load()
    entry.runtime_data = controller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Erst jetzt starten: alle Entitäten sind registriert, die Status-Attribute vollständig
    controller.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Gespeicherten Reglerzustand löschen, wenn die Integration entfernt wird."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Neue Optionen (Entitäten, Takt, Parameter) durch Neuladen übernehmen."""
    await hass.config_entries.async_reload(entry.entry_id)
