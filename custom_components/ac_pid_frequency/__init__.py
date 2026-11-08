"""AC PID Frequency: stellt der Klimaanlage einen vorgetäuschten Raumsensor bereit, mit dem sie auf eine Ziel-Frequenz einpendelt."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CARD_FILE, CARD_URL, DOMAIN, PLATFORMS, STORAGE_VERSION
from .controller import AcPidFrequencyController

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def _async_get_version_url(hass: HomeAssistant) -> str:
    """Ermittelt die versions- und zeitstempelbehaftete Ressourcen-URL der Lovelace-Karte."""
    integration = await async_get_integration(hass, DOMAIN)
    card = Path(__file__).parent / "frontend" / CARD_FILE
    try:
        timestamp = int(card.stat().st_mtime)
    except OSError:
        timestamp = 0
    return f"{CARD_URL}?v={integration.version}_{timestamp}"


async def _async_register_lovelace_resource(hass: HomeAssistant, resource_url: str) -> None:
    """Registriert oder aktualisiert die Karte in den Lovelace-Ressourcen (GUI/Storage-Modus)."""
    try:
        lovelace = hass.data.get("lovelace")
        if not lovelace or not hasattr(lovelace, "resources"):
            return

        resources = lovelace.resources
        # Im YAML-Modus existiert async_create_item nicht
        if not hasattr(resources, "async_create_item"):
            return

        if hasattr(resources, "async_get_info"):
            await resources.async_get_info()
        elif hasattr(resources, "async_load") and not getattr(resources, "loaded", True):
            await resources.async_load()

        # Bestehenden Eintrag anhand der Basis-URL suchen und bei Versionswechsel aktualisieren
        for item in resources.async_items():
            url = item.get("url", "")
            if url == resource_url or url.startswith(CARD_URL):
                if url != resource_url and hasattr(resources, "async_update_item"):
                    await resources.async_update_item(
                        item["id"],
                        {"res_type": "module", "url": resource_url},
                    )
                    _LOGGER.debug("Lovelace-Ressource aktualisiert: %s", resource_url)
                return

        # Neu registrieren
        await resources.async_create_item(
            {"res_type": "module", "url": resource_url}
        )
        _LOGGER.debug("Lovelace-Ressource registriert: %s", resource_url)
    except Exception as err:
        _LOGGER.debug("Lovelace-Ressource konnte nicht automatisch registriert werden: %s", err)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Lovelace-Karte ausliefern und automatisch in alle Dashboards laden."""
    card = Path(__file__).parent / "frontend" / CARD_FILE
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(card), False)])

    version_url = await _async_get_version_url(hass)

    # 1. Extra JS URL (Fallback für YAML-Modus und frühes Laden)
    add_extra_js_url(hass, version_url)

    # 2. Lovelace-Ressourcen (behebt Android Companion App & Cache-Busting ohne STRG+F5)
    async def _register(_: Event | None = None) -> None:
        v_url = await _async_get_version_url(hass)
        await _async_register_lovelace_resource(hass, v_url)

    if hass.state == CoreState.running:
        await _register()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller = AcPidFrequencyController(hass, entry)
    await controller.async_load()
    entry.runtime_data = controller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Erst jetzt starten: alle Entitäten sind registriert, die Status-Attribute vollständig
    controller.async_start()

    # Falls die Integration im laufenden Betrieb neu geladen wurde:
    if hass.state == CoreState.running:
        v_url = await _async_get_version_url(hass)
        await _async_register_lovelace_resource(hass, v_url)

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
