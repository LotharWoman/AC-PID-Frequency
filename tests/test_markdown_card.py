"""Die Beispiel-Markdown-Karte (examples/markdown-card.yaml) rendert mit den Integrationsdaten."""

from __future__ import annotations

from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers.template import Template

from test_integration import (
    CLIMATE, HZ, OUTDOOR, ROOM, _eid, _setup,
)

CARD = Path(__file__).parent.parent / "examples" / "markdown-card.yaml"


def _render(hass: HomeAssistant, entry) -> str:
    content = yaml.safe_load(CARD.read_text(encoding="utf-8"))["content"]
    status = _eid(hass, entry, "sensor", "status")
    content = content.replace("sensor.ac_pid_scm40_status", status)
    return Template(content, hass).async_render(parse_result=False)


async def test_markdown_card_regulating_and_off_and_missing_sensors(hass: HomeAssistant) -> None:
    entry = await _setup(hass, hz="21.0", room="19.7", outdoor="8.0")

    # Regler aus + Raumsensor -> Passthrough
    out = _render(hass, entry)
    print(out)
    assert "Regler AUS" in out
    assert "durchgereicht" in out
    assert "| Raum (real) | **19.7 °C** (-1.3 K zum Soll) |" in out
    assert "| Außen | 8.0 °C |" in out
    assert "| Frequenz | |\n|:--|--:|\n| Ziel | **30 Hz** |" in out
    assert "| Abweichung | -9.0 Hz |" in out
    assert "Wert (simuliert) | 19.7 °C" in out
    assert "Durchgereicht" in out
    assert "Erfahrungswert" not in out

    # Regler an -> Regelung
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _eid(hass, entry, "switch", "enabled")}, blocking=True
    )
    await hass.async_block_till_done()
    out = _render(hass, entry)
    print(out)
    assert "Frequenz zu niedrig" in out
    assert "| Erfahrungswert |" in out
    assert "(d = +" in out

    # Raum- und Außensensor nicht konfiguriert -> Zeilen verschwinden, kein Fehler
    entry2_out = out
    assert "Soll | 21.0 °C" in entry2_out

    # Ausfall der Eingänge: keine Exception, Platzhalter
    hass.states.async_set(HZ, STATE_UNAVAILABLE)
    hass.states.async_set(OUTDOOR, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    out = _render(hass, entry)
    assert "| Ist | **–** |" in out
    assert "| Außen | – |" in out

    # Status-Sensor unbekannt -> freundlicher Hinweis
    content = yaml.safe_load(CARD.read_text(encoding="utf-8"))["content"]
    out = Template(content, hass).async_render(parse_result=False)
    assert "nicht verfügbar" in out
