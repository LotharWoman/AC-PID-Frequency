"""Einrichtung und Umkonfiguration: alle benötigten Entitäten sind frei wählbar."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CLIMATE,
    CONF_DEADBAND,
    CONF_FACTOR_DOWN,
    CONF_FACTOR_FLOOR,
    CONF_FACTOR_MAX,
    CONF_FACTOR_MIN,
    CONF_FACTOR_UP,
    CONF_FAULT_TIMEOUT,
    CONF_FREQUENCY,
    CONF_HOLD_LIMIT,
    CONF_HUNTING,
    CONF_INDOOR_UNITS,
    CONF_INTERVAL,
    CONF_MAX_OFFSET,
    CONF_NAME,
    CONF_OFFSET_BRAKE,
    CONF_OFFSET_LOWER,
    CONF_OFFSET_RAISE,
    CONF_STEP_NORMAL,
    CONF_STEP_RAISE,
    DEFAULT_NAME,
    DOMAIN,
    TUNING_DEFAULTS,
)

FREQUENCY_DOMAINS = ["sensor", "number", "input_number"]

# (Schlüssel, min, max, Schritt, Einheit) – Reihenfolge = Reihenfolge im Dialog
TUNING_FIELDS: list[tuple[str, float, float, float, str]] = [
    (CONF_INTERVAL, 10, 300, 5, "s"),
    (CONF_FAULT_TIMEOUT, 1, 120, 1, "min"),
    (CONF_DEADBAND, 0.5, 10, 0.5, "Hz"),
    (CONF_OFFSET_RAISE, 0, 3, 0.05, "K"),
    (CONF_OFFSET_LOWER, 0, 3, 0.05, "K"),
    (CONF_OFFSET_BRAKE, 0, 3, 0.05, "K"),
    (CONF_HOLD_LIMIT, 0, 2, 0.05, "K"),
    (CONF_STEP_RAISE, 0.01, 1, 0.01, "K/min"),
    (CONF_STEP_NORMAL, 0.01, 1, 0.01, "K/min"),
    (CONF_MAX_OFFSET, 0.1, 5, 0.1, "K"),
    (CONF_HUNTING, 0.5, 20, 0.5, "Hz"),
    (CONF_FACTOR_MIN, 0.1, 2, 0.05, ""),
    (CONF_FACTOR_MAX, 0.5, 3, 0.05, ""),
    (CONF_FACTOR_FLOOR, 0.1, 2, 0.05, ""),
    (CONF_FACTOR_DOWN, 0.01, 0.5, 0.01, ""),
    (CONF_FACTOR_UP, 0.01, 0.5, 0.01, ""),
]


def _entity_selector(domain: str | list[str], multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, multiple=multiple)
    )


def _entities_schema(with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = selector.TextSelector()
    fields[vol.Required(CONF_CLIMATE)] = _entity_selector("climate")
    fields[vol.Required(CONF_FREQUENCY)] = _entity_selector(FREQUENCY_DOMAINS)
    fields[vol.Optional(CONF_INDOOR_UNITS)] = _entity_selector("climate", multiple=True)
    return vol.Schema(fields)


def _tuning_schema() -> vol.Schema:
    fields: dict[Any, Any] = {}
    for key, low, high, step, unit in TUNING_FIELDS:
        config = selector.NumberSelectorConfig(
            min=low,
            max=high,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
        )
        if unit:  # None wird vom Selector abgelehnt, daher nur setzen, wenn vorhanden
            config["unit_of_measurement"] = unit
        fields[vol.Required(key)] = selector.NumberSelector(config)
    return vol.Schema(fields)


def _clean_indoor_units(user_input: dict[str, Any]) -> list[str]:
    """Weitere Innengeräte ohne das Master-Gerät und ohne Doppelte."""
    master = user_input.get(CONF_CLIMATE)
    seen: list[str] = []
    for entity_id in user_input.get(CONF_INDOOR_UNITS) or []:
        if entity_id != master and entity_id not in seen:
            seen.append(entity_id)
    return seen


class AcPidFrequencyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ersteinrichtung."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_CLIMATE])
            self._abort_if_unique_id_configured()
            data = {**user_input, CONF_INDOOR_UNITS: _clean_indoor_units(user_input)}
            return self.async_create_entry(title=user_input[CONF_NAME], data=data)

        return self.async_show_form(step_id="user", data_schema=_entities_schema(with_name=True))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AcPidFrequencyOptionsFlow:
        return AcPidFrequencyOptionsFlow()


class AcPidFrequencyOptionsFlow(OptionsFlow):
    """Nachträglich umkonfigurieren: Entitäten oder Regelparameter."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["entities", "tuning"])

    def _current(self) -> dict[str, Any]:
        return {**TUNING_DEFAULTS, **self.config_entry.data, **self.config_entry.options}

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = {
                **self.config_entry.options,
                CONF_CLIMATE: user_input[CONF_CLIMATE],
                CONF_FREQUENCY: user_input[CONF_FREQUENCY],
                CONF_INDOOR_UNITS: _clean_indoor_units(user_input),
            }
            return self.async_create_entry(data=options)

        schema = self.add_suggested_values_to_schema(
            _entities_schema(with_name=False), self._current()
        )
        return self.async_show_form(step_id="entities", data_schema=schema)

    async def async_step_tuning(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not (
                user_input[CONF_FACTOR_MIN]
                <= user_input[CONF_FACTOR_FLOOR]
                <= user_input[CONF_FACTOR_MAX]
            ):
                errors["base"] = "invalid_factor_range"
            else:
                return self.async_create_entry(data={**self.config_entry.options, **user_input})

        suggested = user_input if user_input is not None else self._current()
        schema = self.add_suggested_values_to_schema(_tuning_schema(), suggested)
        return self.async_show_form(step_id="tuning", data_schema=schema, errors=errors)
