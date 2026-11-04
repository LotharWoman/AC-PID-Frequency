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
    CONF_DEFROST,
    CONF_FREQUENCY,
    CONF_INDOOR_UNITS,
    CONF_OUTDOOR_TEMP,
    CONF_ROOM_TEMP,
    DOMAIN,
    TUNING_DEFAULTS,
)

CLIMATE = "climate.master"
HZ = "sensor.compressor_hz"
OUTDOOR = "sensor.outdoor_temp"
ROOM = "sensor.real_room_temp"
DEFROST = "binary_sensor.defrost"


def _entry(**extra) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Klima Test",
        unique_id=CLIMATE,
        data={
            "name": "Klima Test",
            CONF_CLIMATE: CLIMATE,
            CONF_FREQUENCY: HZ,
            CONF_OUTDOOR_TEMP: OUTDOOR,
            CONF_ROOM_TEMP: ROOM,
            CONF_DEFROST: DEFROST,
            CONF_INDOOR_UNITS: ["climate.zimmer2"],
            **extra,
        },
    )


def _eid(hass: HomeAssistant, entry, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"{platform}/{key} nicht registriert"
    return entity_id


async def _setup(hass: HomeAssistant, climate_state="heat", setpoint=21.0, hz="10", outdoor="8.0", room="20.5", defrost="off"):
    hass.states.async_set(CLIMATE, climate_state, {"temperature": setpoint})
    hass.states.async_set(HZ, hz)
    hass.states.async_set(OUTDOOR, outdoor)
    hass.states.async_set(ROOM, room)
    hass.states.async_set(DEFROST, defrost)
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
        CONF_OUTDOOR_TEMP: OUTDOOR,
        CONF_ROOM_TEMP: ROOM,
        CONF_DEFROST: DEFROST,
        CONF_INDOOR_UNITS: [CLIMATE, "climate.zimmer2", "climate.zimmer2"],
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Klima Flur"
    assert result["data"][CONF_INDOOR_UNITS] == ["climate.zimmer2"]
    assert result["data"][CONF_OUTDOOR_TEMP] == OUTDOOR
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_sensor_unavailable_while_controller_off_without_room_value(
    hass: HomeAssistant,
) -> None:
    """Regler aus und keine echte Raumtemperatur -> Sensor unavailable (Anlage-Eigensensor)."""
    entry = await _setup(hass, room=STATE_UNAVAILABLE)
    sensor = _eid(hass, entry, "sensor", "temperature")
    assert hass.states.get(sensor).state == STATE_UNAVAILABLE
    status = hass.states.get(_eid(hass, entry, "sensor", "status"))
    assert status.state == "off"


async def test_intelligent_regulation_and_dead_time(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="10", outdoor="8.0")
    sensor = _eid(hass, entry, "sensor", "temperature")
    switch = _eid(hass, entry, "switch", "enabled")

    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    # Soll 21.0, Outdoor 8.0 -> normal/mid_low (learned 0.35) -> Start bei 20.7
    assert hass.states.get(sensor).state == "20.7"
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "raise"

    # Nach 60 s (unter 120s Reaktionszeit) -> hält Wert
    await _tick(hass, 61)
    assert hass.states.get(sensor).state == "20.7"

    # Nach 121 s -> Totzeit verstrichen, Frequenz stagniert noch bei 10 -> Schritt um 0,1 K kälter
    await _tick(hass, 61)
    assert hass.states.get(sensor).state == "20.6"

    # Frequenz schießt hoch auf 50 Hz -> Mode lower
    hass.states.async_set(HZ, "50")
    await _tick(hass, 61)
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "lower"


async def test_defrost_pauses_regulation(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="75", defrost="on")
    sensor = _eid(hass, entry, "sensor", "temperature")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    # Im Defrost wird Mode defrost gemeldet und keine Notbremse ausgelöst
    status = hass.states.get(_eid(hass, entry, "sensor", "status"))
    assert status.state == "defrost"


async def test_overheat_protection_triggers(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="30", room="22.5")  # Soll 21.0, Raum 22.5 > 21 + 1.0
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    status = hass.states.get(_eid(hass, entry, "sensor", "status"))
    assert status.state == "overheat"


async def test_sensor_unavailable_when_not_heating_without_room_value(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, room=STATE_UNAVAILABLE)
    sensor = _eid(hass, entry, "sensor", "temperature")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state != STATE_UNAVAILABLE

    hass.states.async_set(CLIMATE, "off", {"temperature": 21.0})
    await hass.async_block_till_done()
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
    assert hass.states.get(sensor).state == held

    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(status).state == "fault"
    assert hass.states.get(sensor).state == STATE_UNAVAILABLE


async def test_numbers_and_status_attributes(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    brake = _eid(hass, entry, "number", "brake_hz")
    target = _eid(hass, entry, "number", "target_hz")
    assert float(hass.states.get(brake).state) == 70.0

    await hass.services.async_call(
        "number", "set_value", {"entity_id": brake, "value": 62}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": target, "value": 25}, blocking=True
    )
    assert float(hass.states.get(brake).state) == 62.0
    assert float(hass.states.get(target).state) == 25.0

    attrs = hass.states.get(_eid(hass, entry, "sensor", "status")).attributes
    assert attrs["ac_pid_frequency_climate"] == CLIMATE
    assert attrs["frequency_entity"] == HZ
    assert attrs["outdoor_temperature_entity"] == OUTDOOR
    assert attrs["room_temperature_entity"] == ROOM
    assert attrs["defrost_entity"] == DEFROST
    assert attrs["target_hz_entity"] == target
    assert attrs["brake_hz_entity"] == brake


async def test_learned_state_survives_restart(hass: HomeAssistant, hass_storage) -> None:
    entry = await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    # Manuell einen gelernten Wert setzen
    entry.runtime_data.regelung.learned_table["normal"]["mid_low"] = 0.42
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    controller = entry.runtime_data
    assert controller.enabled is True
    assert controller.regelung.learned_table["normal"]["mid_low"] == 0.42


async def test_reset_learning_button(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    entry.runtime_data.regelung.learned_table["normal"]["mid_low"] = 0.88
    await hass.services.async_call(
        "button", "press", {"entity_id": _eid(hass, entry, "button", "reset_learning")},
        blocking=True,
    )
    assert entry.runtime_data.regelung.learned_table["normal"]["mid_low"] == 0.35


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
        {
            CONF_CLIMATE: "climate.neu",
            CONF_FREQUENCY: "sensor.hz_neu",
            CONF_OUTDOOR_TEMP: "sensor.aussen_neu",
        },
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.config[CONF_CLIMATE] == "climate.neu"
    assert entry.runtime_data.config[CONF_OUTDOOR_TEMP] == "sensor.aussen_neu"

    # Parameter anpassen
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "tuning"}
    )
    assert flow["step_id"] == "tuning"
    good = {**TUNING_DEFAULTS, "interval_s": 30, "reaction_time_s": 150}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], good)
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    params = entry.runtime_data.params
    assert params.interval_s == 30 and params.reaction_time_s == 150


async def test_card_is_served(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, "http", {})
    entry = await _setup(hass)
    client = await hass_client()
    response = await client.get("/ac_pid_frequency/ac-pid-frequency-card.js")
    assert response.status == 200
    body = await response.text()
    assert "ac-pid-frequency-card" in body
    assert entry.state is ConfigEntryState.LOADED


# --------------------------------------------------------------------------------------
# Durchreichen der echten Raumtemperatur (Passthrough)
# --------------------------------------------------------------------------------------
async def test_passthrough_when_controller_off_follows_room_sensor_immediately(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, room="20.74")
    sensor = _eid(hass, entry, "sensor", "temperature")
    status = hass.states.get(_eid(hass, entry, "sensor", "status"))
    assert status.state == "off"
    assert status.attributes["passthrough"] is True
    assert hass.states.get(sensor).state == "20.7"  # auf 0,1 gerundet
    assert float(hass.states.get(_eid(hass, entry, "sensor", "offset")).state) == 0.0

    # Änderung wird ohne Taktverzögerung weitergegeben
    hass.states.async_set(ROOM, "21.26")
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "21.3"

    # Raumsensor fällt aus -> erst jetzt unavailable (Anlage nutzt eigenen Sensor)
    hass.states.async_set(ROOM, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == STATE_UNAVAILABLE
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).attributes["passthrough"] is False

    hass.states.async_set(ROOM, "20.0")
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "20.0"


async def test_passthrough_when_not_heating_then_regulation_takes_over(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, climate_state="cool", room="22.4")
    sensor = _eid(hass, entry, "sensor", "temperature")
    status = _eid(hass, entry, "sensor", "status")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    # Regler an, aber Anlage kühlt -> echte Raumtemperatur
    assert hass.states.get(status).state == "idle"
    assert hass.states.get(sensor).state == "22.4"

    # Anlage wechselt in den Heizbetrieb -> Regelung übernimmt sofort
    hass.states.async_set(CLIMATE, "heat", {"temperature": 21.0})
    await hass.async_block_till_done()
    assert hass.states.get(status).state != "idle"
    assert hass.states.get(status).attributes["passthrough"] is False
    assert hass.states.get(sensor).state != "22.4"

    # ... und zurück: wieder durchreichen
    hass.states.async_set(CLIMATE, "off", {"temperature": 21.0})
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "22.4"


async def test_room_change_does_not_trigger_extra_regulation_step(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    regelung = entry.runtime_data.regelung
    before = regelung.time_since_last_step

    hass.states.async_set(ROOM, "20.6")
    await hass.async_block_till_done()
    assert regelung.time_since_last_step == before  # kein zusätzlicher Regelschritt


async def test_fault_stays_unavailable_even_with_room_sensor(
    hass: HomeAssistant, freezer
) -> None:
    """Fehlt das Hz-Signal zu lange, bleibt der Sensor bewusst unavailable."""
    entry = await _setup(hass, room="20.5")
    sensor = _eid(hass, entry, "sensor", "temperature")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    hass.states.async_set(HZ, STATE_UNAVAILABLE)
    for minutes in (2, 10):  # erst Fehlerbeginn merken, dann Wartezeit überschreiten
        freezer.tick(timedelta(minutes=minutes))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "fault"
    assert hass.states.get(sensor).state == STATE_UNAVAILABLE


# ---------------------------------------------------------------------- Hz-Deckel (Regler aus)
async def test_cap_switch_exists_and_defaults_to_on(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    assert hass.states.get(_eid(hass, entry, "switch", "cap_enabled")).state == "on"
    assert entry.runtime_data.cap_enabled is True


async def test_cap_inactive_below_brake_passes_room_through(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="60", room="18.8")
    await _tick(hass, 60)
    status = hass.states.get(_eid(hass, entry, "sensor", "status"))
    assert status.state == "off"
    assert hass.states.get(_eid(hass, entry, "sensor", "temperature")).state == "18.8"
    assert status.attributes["cap_active"] is False


async def test_cap_takes_over_above_brake_and_releases(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="60", room="18.8")
    temp = _eid(hass, entry, "sensor", "temperature")
    status = _eid(hass, entry, "sensor", "status")
    learned_before = {
        k: dict(v) for k, v in entry.runtime_data.regelung.learned_table.items()
    }

    # Anlage regelt mit kalter echter Temperatur selbst und fährt über die Notbremse
    hass.states.async_set(HZ, "84")
    await _tick(hass, 60)
    assert hass.states.get(status).state == "cap"
    assert hass.states.get(status).attributes["cap_active"] is True
    assert hass.states.get(status).attributes["passthrough"] is False
    assert float(hass.states.get(temp).state) == 21.5  # Soll 21,0 + Notbremse-Offset 0,5

    # Auch bei weiter steigender echter Temperatur bleibt der Deckel, solange Hz hoch
    hass.states.async_set(ROOM, "19.2")
    await _tick(hass, 60)
    assert hass.states.get(status).state == "cap"
    assert float(hass.states.get(temp).state) == 21.5

    # Hz sinken unter die Notbremse: Deckel hält (Echtwert noch kalt) statt sofort durchzureichen
    hass.states.async_set(HZ, "66")
    await _tick(hass, 60)
    assert hass.states.get(status).state == "cap"
    assert float(hass.states.get(temp).state) >= 21.0

    # Raum wird warm genug: Deckel gibt frei und die echte Temperatur wird wieder durchgereicht
    hass.states.async_set(ROOM, "22.0")
    await _tick(hass, 60)
    assert hass.states.get(status).state == "off"
    assert hass.states.get(temp).state == "22.0"
    assert hass.states.get(status).attributes["cap_active"] is False

    # Der Deckel hat nichts in die gelernte Tabelle zurückgeschrieben
    assert entry.runtime_data.regelung.learned_table == learned_before


async def test_cap_never_sends_less_than_real_room_temperature(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="84", room="23.0")
    await _tick(hass, 60)
    temp = hass.states.get(_eid(hass, entry, "sensor", "temperature"))
    assert float(temp.state) >= 23.0


async def test_cap_can_be_switched_off(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="84", room="18.8")
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": _eid(hass, entry, "switch", "cap_enabled")}, blocking=True
    )
    await _tick(hass, 60)
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "off"
    assert hass.states.get(_eid(hass, entry, "sensor", "temperature")).state == "18.8"


async def test_cap_pauses_during_defrost_and_when_not_heating(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="84", room="18.8", defrost="on")
    await _tick(hass, 60)
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "off"
    assert hass.states.get(_eid(hass, entry, "sensor", "temperature")).state == "18.8"

    hass.states.async_set(DEFROST, "off")
    await _tick(hass, 60)
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "cap"

    hass.states.async_set(CLIMATE, "off", {"temperature": 21.0})
    await _tick(hass, 60)
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "off"
    assert hass.states.get(_eid(hass, entry, "sensor", "temperature")).state == "18.8"


async def test_turning_regulation_on_ends_cap(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="84", room="18.8")
    await _tick(hass, 60)
    assert entry.runtime_data.cap_active is True
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.cap_active is False
    assert hass.states.get(_eid(hass, entry, "sensor", "status")).state == "brake"


async def test_cap_state_persists_setting(hass: HomeAssistant, hass_storage) -> None:
    entry = await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": _eid(hass, entry, "switch", "cap_enabled")}, blocking=True
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.cap_enabled is False
