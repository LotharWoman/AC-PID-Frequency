"""Controller: verbindet den Regelkern mit Home Assistant.

* liest Soll-Temperatur (Master-Climate) und Kompressor-Hz,
* liest optional Außentemperatur, echten Raumtemperatursensor und Abtaustatus,
* rechnet im eingestellten Takt einen Regelschritt,
* stellt das Ergebnis als Sensorwert bereit (Entitäten holen es sich vom Controller),
* speichert 2D-Lerntabelle, Sensorwert und Einstellungen über Neustarts hinweg.

Fehlerverhalten: Fehlen Eingangsdaten, wird der letzte Wert zunächst gehalten
(Status ``waiting``). Dauert das länger als ``fault_timeout_min``, wird der Sensor
``unavailable`` (Status ``fault``) und die Anlage fällt auf ihren eigenen Innensensor
zurück.

Durchreichen (Passthrough): Ist der Regler aus oder die Anlage nicht im Heizbetrieb und ist
ein echter Raumtemperatursensor konfiguriert, der einen gültigen Wert liefert, gibt der
erzeugte Sensor dessen Wert 1:1 weiter (Offset 0,0 K) und folgt jeder Änderung sofort. So
rechnet die Anlage weiter mit dem echten Raumthermometer statt mit ihrem Deckensensor. Nur
wenn auch dieser Wert fehlt (oder gar kein Raumsensor konfiguriert ist), wird der Sensor
``unavailable``.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BRAKE_HZ_MAX,
    BRAKE_HZ_MIN,
    CONF_CLIMATE,
    CONF_DEADBAND,
    CONF_DEFROST,
    CONF_FAULT_TIMEOUT,
    CONF_FREQUENCY,
    CONF_INTERVAL,
    CONF_MAX_OFFSET,
    CONF_MAX_ROOM_OVERHEAT,
    CONF_OFFSET_BRAKE,
    CONF_OUTDOOR_TEMP,
    CONF_REACTION_TIME,
    CONF_ROOM_TEMP,
    DEFAULT_BRAKE_HZ,
    DEFAULT_TARGET_HZ,
    DOMAIN,
    HVAC_MODE_ACTIVE,
    STATUS_FAULT,
    STATUS_IDLE,
    STATUS_OFF,
    STATUS_WAITING,
    STORAGE_VERSION,
    TARGET_HZ_MAX,
    TARGET_HZ_MIN,
    TUNING_DEFAULTS,
)
from .regelung import Params, State, round1, step

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY_S = 30


def _to_float(value: Any) -> float | None:
    """Zahl aus Zustand/Attribut lesen; ``unavailable``/``unknown``/Müll -> None."""
    if value is None or value in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class AcPidFrequencyController:
    """Hält Zustand und Zeitgeber von AC PID Frequency (ein Config-Entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._unsubs: list = []
        self._fault_since: datetime | None = None

        self.signal = f"{DOMAIN}_update_{entry.entry_id}"
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Eigenbau",
            model="AC PID Frequency",
        )

        # Regelkern-Zustand (inkl. gelernter Arbeitspunkt-Tabelle)
        self.regelung = State()

        # Vom Nutzer einstellbar (per Entität), werden gespeichert
        self.enabled = False
        self.target_hz: float = float(DEFAULT_TARGET_HZ)
        self.brake_hz: float = float(DEFAULT_BRAKE_HZ)

        # Ergebnis des letzten Taktes (für die Entitäten)
        self.status = STATUS_OFF
        self.available = False
        self.output: float | None = None
        self.offset: float | None = None
        self.error_hz: float | None = None
        self.passthrough = False  # True: Sensor spiegelt gerade die echte Raumtemperatur

    # ------------------------------------------------------------------ Konfiguration
    @property
    def config(self) -> dict[str, Any]:
        """Setup-Daten, überschrieben von den Optionen, mit Standardwerten dahinter."""
        return {**TUNING_DEFAULTS, **self.entry.data, **self.entry.options}

    @property
    def params(self) -> Params:
        c = self.config
        return Params(
            interval_s=float(c[CONF_INTERVAL]),
            reaction_time_s=float(c[CONF_REACTION_TIME]),
            deadband_hz=float(c[CONF_DEADBAND]),
            offset_brake=float(c[CONF_OFFSET_BRAKE]),
            max_offset=float(c[CONF_MAX_OFFSET]),
            max_room_overheat=float(c[CONF_MAX_ROOM_OVERHEAT]),
        )

    # ------------------------------------------------------------------ Lebenszyklus
    async def async_load(self) -> None:
        """Gespeicherten Zustand laden."""
        data = await self._store.async_load() or {}
        self.enabled = bool(data.get("enabled", False))
        target = _to_float(data.get("target_hz"))
        brake = _to_float(data.get("brake_hz"))
        output = _to_float(data.get("output"))
        if target is not None:
            self.target_hz = min(max(target, TARGET_HZ_MIN), TARGET_HZ_MAX)
        if brake is not None:
            self.brake_hz = min(max(brake, BRAKE_HZ_MIN), BRAKE_HZ_MAX)
        self.regelung.output = output

        learned_table = data.get("learned_table")
        if isinstance(learned_table, dict):
            self.regelung.load_learned_table(learned_table)

    @callback
    def async_start(self) -> None:
        """Zeitgeber und Beobachter starten, sofort einen ersten Takt rechnen."""
        cfg = self.config
        interval = timedelta(seconds=max(5.0, float(cfg[CONF_INTERVAL])))
        self._unsubs.append(async_track_time_interval(self.hass, self._handle_tick, interval))
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [cfg[CONF_CLIMATE]], self._handle_climate_change
            )
        )
        if cfg.get(CONF_ROOM_TEMP):
            # Echte Raumtemperatur sofort durchreichen, ohne auf den nächsten Takt zu warten
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [cfg[CONF_ROOM_TEMP]], self._handle_room_change
                )
            )
        self._tick()

    async def async_shutdown(self) -> None:
        """Zeitgeber stoppen und Zustand sichern."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data_to_save())

    async def async_remove_storage(self) -> None:
        await self._store.async_remove()

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "target_hz": self.target_hz,
            "brake_hz": self.brake_hz,
            "output": self.regelung.output,
            "learned_table": self.regelung.learned_table,
        }

    # ------------------------------------------------------------------ Bedienung
    @callback
    def async_set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._tick()

    @callback
    def async_set_target_hz(self, value: float) -> None:
        self.target_hz = float(min(max(value, TARGET_HZ_MIN), TARGET_HZ_MAX))
        self._publish()

    @callback
    def async_set_brake_hz(self, value: float) -> None:
        self.brake_hz = float(min(max(value, BRAKE_HZ_MIN), BRAKE_HZ_MAX))
        self._publish()

    @callback
    def async_reset_learning(self) -> None:
        """Setzt die gelernte Arbeitspunkt-Tabelle auf Werkseinstellungen zurück."""
        self.regelung.reset_learning()
        self._publish()

    # ------------------------------------------------------------------ Takt
    @callback
    def _handle_tick(self, _now: datetime) -> None:
        self._tick()

    @callback
    def _handle_climate_change(self, event: Event[EventStateChangedData]) -> None:
        """Beim Wechsel in/aus dem Heizbetrieb sofort reagieren statt auf den Takt zu warten."""
        old, new = event.data["old_state"], event.data["new_state"]
        was_active = old is not None and old.state == HVAC_MODE_ACTIVE
        is_active = new is not None and new.state == HVAC_MODE_ACTIVE
        if was_active != is_active:
            self._tick()

    @callback
    def _handle_room_change(self, event: Event[EventStateChangedData]) -> None:
        """Raumtemperatur geändert: nur im Durchreich-Betrieb sofort nachziehen.

        Bei laufender Regelung bleibt es beim Takt, damit kein zusätzlicher Regelschritt
        ausgelöst wird.
        """
        if self.status in (STATUS_OFF, STATUS_IDLE):
            self._tick()

    @callback
    def _tick(self) -> None:
        self._evaluate()
        self._publish()

    @callback
    def _publish(self) -> None:
        """Entitäten benachrichtigen und Zustand verzögert speichern."""
        async_dispatcher_send(self.hass, self.signal)
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY_S)

    def _evaluate(self) -> None:
        """Einen Regelschritt rechnen (oder den Fehlerfall behandeln)."""
        cfg = self.config

        if not self.enabled:
            self._set_passive(STATUS_OFF)
            return

        climate = self.hass.states.get(cfg[CONF_CLIMATE])
        climate_ok = climate is not None and climate.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )
        if climate_ok and climate.state != HVAC_MODE_ACTIVE:
            # Anlage aus / kühlt / ... -> echte Raumtemperatur durchreichen (falls vorhanden),
            # sonst Sensor sofort weg, die Anlage nutzt ihren eigenen
            self._set_passive(STATUS_IDLE)
            return

        setpoint = _to_float(climate.attributes.get("temperature")) if climate_ok else None
        freq = self.hass.states.get(cfg[CONF_FREQUENCY])
        hz = _to_float(freq.state) if freq is not None else None
        if setpoint is None or hz is None:
            self._handle_missing_data()
            return

        # Optionale Eingangsgrößen lesen
        outdoor_temp: float | None = None
        outdoor_ent = cfg.get(CONF_OUTDOOR_TEMP)
        if outdoor_ent:
            out_state = self.hass.states.get(outdoor_ent)
            if out_state is not None and out_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                if out_state.domain == "weather":
                    outdoor_temp = _to_float(out_state.attributes.get("temperature"))
                else:
                    outdoor_temp = _to_float(out_state.state)

        room_temp = self._configured_room_temp()
        if room_temp is None and not cfg.get(CONF_ROOM_TEMP) and climate_ok:
            room_temp = _to_float(climate.attributes.get("current_temperature"))

        defrost = False
        defrost_ent = cfg.get(CONF_DEFROST)
        if defrost_ent:
            def_state = self.hass.states.get(defrost_ent)
            if def_state is not None and def_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                defrost = def_state.state.lower() in ("on", "true", "defrost", "defrosting")
        elif climate_ok:
            action = str(climate.attributes.get("hvac_action") or "").lower()
            defrost = action in ("defrosting", "preheating")

        self._fault_since = None
        result = step(
            self.params,
            self.regelung,
            setpoint,
            hz,
            self.target_hz,
            self.brake_hz,
            outdoor_temp=outdoor_temp,
            room_temp=room_temp,
            defrost=defrost,
        )
        self.available = True
        self.passthrough = False
        self.output = result.published
        self.offset = result.offset
        self.error_hz = result.error_hz
        self.status = result.mode
        _LOGGER.debug(
            "Takt: soll=%.1f hz=%.1f ziel=%.0f -> %s, sensor=%.1f (offset %.2f, gelernt %.2f K [%s/%s])",
            setpoint,
            hz,
            min(self.target_hz, self.brake_hz),
            result.mode,
            result.published,
            result.offset,
            result.learned_offset,
            result.outdoor_bin,
            result.freq_bin,
        )

    def _configured_room_temp(self) -> float | None:
        """Wert des konfigurierten echten Raumtemperatursensors (None, wenn keiner/ungültig)."""
        entity_id = self.config.get(CONF_ROOM_TEMP)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        return _to_float(state.state) if state is not None else None

    def _set_passive(self, status: str) -> None:
        """Nicht regeln: echte Raumtemperatur durchreichen oder (ohne sie) unavailable."""
        self._set_inactive(status)
        room_temp = self._configured_room_temp()
        if room_temp is not None:
            self.available = True
            self.passthrough = True
            self.output = round1(room_temp)
            self.offset = 0.0

    def _set_inactive(self, status: str) -> None:
        self.passthrough = False
        self.available = False
        self.output = self.offset = self.error_hz = None
        self.status = status
        self._fault_since = None
        self.regelung.hz_prev1 = self.regelung.hz_prev2 = None

    def _handle_missing_data(self) -> None:
        """Eingangsdaten fehlen: erst Wert halten, nach Zeitlimit unavailable."""
        now = dt_util.utcnow()
        if self._fault_since is None:
            self._fault_since = now
        timeout = timedelta(minutes=float(self.config[CONF_FAULT_TIMEOUT]))
        if now - self._fault_since >= timeout:
            if self.status != STATUS_FAULT:
                _LOGGER.warning(
                    "Eingangsdaten fehlen seit %s min – Sensor wird unavailable, "
                    "die Anlage nutzt ihren eigenen Innensensor",
                    self.config[CONF_FAULT_TIMEOUT],
                )
            self.available = False
            self.passthrough = False
            self.output = self.offset = self.error_hz = None
            self.status = STATUS_FAULT
            self.regelung.hz_prev1 = self.regelung.hz_prev2 = None
        else:
            self.status = STATUS_WAITING
