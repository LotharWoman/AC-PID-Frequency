"""Integrationstests gegen ein echtes (Test-)Home-Assistant."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ac_pid_frequency.const import (
    CONF_CLIMATE,
    CONF_FREQUENCY,
    CONF_INDOOR_UNITS,
    DOMAIN,
    TUNING_DEFAULTS,
)

CLIMATE = "climate.master"
HZ = "sensor.compressor_hz"


def _entry(**extra) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Klima Test",
        unique_id=CLIMATE,
        data={
            "name": "Klima Test",
            CONF_CLIMATE: CLIMATE,
            CONF_FREQUENCY: HZ,
            CONF_INDOOR_UNITS: ["climate.zimmer2"],
            **extra,
        },
    )


def _eid(hass: HomeAssistant, entry, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"{platform}/{key} nicht registriert"
    return entity_id


async def _setup(hass: HomeAssistant, climate_state="heat", setpoint=21.0, hz="10"):
    hass.states.async_set(CLIMATE, climate_state, {"temperature": setpoint})
    hass.states.async_set(HZ, hz)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _tick(hass: HomeAssistant, seconds: int) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
async def test_config_flow_creates_entry_and_rejects_duplicate(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    user_input = {
        "name": "Klima Flur",
        CONF_CLIMATE: CLIMATE,
        CONF_FREQUENCY: HZ,
        CONF_INDOOR_UNITS: [CLIMATE, "climate.zimmer2", "climate.zimmer2"],
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Klima Flur"
    # Master und Doppelte werden aus der Innengeräte-Liste entfernt
    assert result["data"][CONF_INDOOR_UNITS] == ["climate.zimmer2"]
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_sensor_unavailable_while_controller_off(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    sensor = _eid(hass, entry, "sensor", "temperature")
    assert hass.states.get(sensor).state == STATE_UNAVAILABLE
    status = hass.states.get(_eid(hass, entry, "sensor", "status"))
    assert status.state == "off"


async def test_regulation_follows_yaml_logic(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="10")
    sensor = _eid(hass, entry, "sensor", "temperature")
    switch = _eid(hass, entry, "switch", "enabled")

    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    # Soll 21,0; Hz 10 < Ziel 30 -> sofort ein Schritt von 0,1 K nach unten
    assert hass.states.get(sensor).state == "20.9"
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "raise"

    await _tick(hass, 61)
    assert hass.states.get(sensor).state == "20.8"
    await _tick(hass, 122)
    assert hass.states.get(sensor).state == "20.7"

    # Frequenz deutlich über Ziel -> Sensor springt sofort wärmer als Soll (Soll + 0,4*Faktor)
    hass.states.async_set(HZ, "50")
    await _tick(hass, 183)
    assert float(hass.states.get(sensor).state) > 21.0
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "lower"


async def test_sensor_unavailable_when_not_heating(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    sensor = _eid(hass, entry, "sensor", "temperature")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state != STATE_UNAVAILABLE

    hass.states.async_set(CLIMATE, "off", {"temperature": 21.0})
    await hass.async_block_till_done()  # Wechsel aus dem Heizbetrieb wirkt sofort
    assert hass.states.get(sensor).state == STATE_UNAVAILABLE
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "idle"

    hass.states.async_set(CLIMATE, "heat", {"temperature": 21.0})
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state != STATE_UNAVAILABLE


async def test_missing_data_holds_value_then_goes_unavailable(
    hass: HomeAssistant, freezer
) -> None:
    entry = await _setup(hass)
    sensor = _eid(hass, entry, "sensor", "temperature")
    status = _eid(hass, entry, "sensor", "status")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    held = hass.states.get(sensor).state
    assert held != STATE_UNAVAILABLE

    hass.states.async_set(HZ, STATE_UNAVAILABLE)
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(status).state == "waiting"
    assert hass.states.get(sensor).state == held  # gehalten

    freezer.tick(timedelta(minutes=10))  # Standard-Wartezeit 10 min überschritten
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(status).state == "fault"
    assert hass.states.get(sensor).state == STATE_UNAVAILABLE

    # Daten kommen zurück -> Regler regelt wieder
    hass.states.async_set(HZ, "10")
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state != STATE_UNAVAILABLE


async def test_numbers_and_status_attributes(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    brake = _eid(hass, entry, "number", "brake_hz")
    target = _eid(hass, entry, "number", "target_hz")
    assert float(hass.states.get(brake).state) == 70.0  # Standard

    await hass.services.async_call(
        "number", "set_value", {"entity_id": brake, "value": 62}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": target, "value": 25}, blocking=True
    )
    assert float(hass.states.get(brake).state) == 62.0
    assert float(hass.states.get(target).state) == 25.0
    assert entry.runtime_data.brake_hz == 62.0

    attrs = hass.states.get(_eid(hass, entry, "sensor", "status")).attributes
    assert attrs["ac_pid_frequency_climate"] == CLIMATE
    assert attrs["frequency_entity"] == HZ
    assert attrs["indoor_units"] == ["climate.zimmer2"]
    assert attrs["target_hz_entity"] == target
    assert attrs["brake_hz_entity"] == brake
    assert attrs["switch_entity"] == _eid(hass, entry, "switch", "enabled")
    assert attrs["temperature_entity"] == _eid(hass, entry, "sensor", "temperature")


async def test_state_survives_restart(hass: HomeAssistant, hass_storage) -> None:
    entry = await _setup(hass)
    brake = _eid(hass, entry, "number", "brake_hz")
    target = _eid(hass, entry, "number", "target_hz")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": brake, "value": 66}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": target, "value": 24}, blocking=True
    )
    entry.runtime_data.regelung.factor = 0.85
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    controller = entry.runtime_data
    assert controller.enabled is True
    assert controller.brake_hz == 66.0
    assert controller.target_hz == 24.0
    assert controller.regelung.factor == 0.85
    assert controller.regelung.output is not None


async def test_reset_learning_button(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    entry.runtime_data.regelung.factor = 0.7
    await hass.services.async_call(
        "button", "press", {"entity_id": _eid(hass, entry, "button", "reset_learning")},
        blocking=True,
    )
    assert entry.runtime_data.regelung.factor == 1.0


async def test_options_flow_entities_and_tuning(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.MENU

    # Entitäten umstellen
    hass.states.async_set("climate.neu", "heat", {"temperature": 22.0})
    hass.states.async_set("sensor.hz_neu", "20")
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "entities"}
    )
    assert flow["type"] is FlowResultType.FORM and flow["step_id"] == "entities"
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {CONF_CLIMATE: "climate.neu", CONF_FREQUENCY: "sensor.hz_neu"},
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.config[CONF_CLIMATE] == "climate.neu"
    assert entry.runtime_data.config[CONF_INDOOR_UNITS] == []  # leer gelassen -> entfernt

    # Parameter: ungültiger Lernfaktor-Bereich wird abgelehnt
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "tuning"}
    )
    assert flow["step_id"] == "tuning"
    bad = {**TUNING_DEFAULTS, "factor_min": 1.1, "factor_floor": 0.8, "factor_max": 1.2}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], bad)
    assert flow["type"] is FlowResultType.FORM
    assert flow["errors"] == {"base": "invalid_factor_range"}

    good = {**TUNING_DEFAULTS, "interval_s": 30, "deadband_hz": 4.0}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], good)
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    params = entry.runtime_data.params
    assert params.interval_s == 30 and params.deadband_hz == 4.0


async def test_card_is_served(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, "http", {})
    entry = await _setup(hass)
    client = await hass_client()
    response = await client.get("/ac_pid_frequency/ac-pid-frequency-card.js")
    assert response.status == 200
    body = await response.text()
    assert "ac-pid-frequency-card" in body
    assert entry.state is ConfigEntryState.LOADED
