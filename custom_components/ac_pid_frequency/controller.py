"""Controller: verbindet den Regelkern mit Home Assistant.

* liest Soll-Temperatur (Master-Climate) und Kompressor-Hz,
* rechnet im eingestellten Takt einen Regelschritt,
* stellt das Ergebnis als Sensorwert bereit (Entitäten holen es sich vom Controller),
* speichert Lernfaktor, Sensorwert und Einstellungen über Neustarts hinweg.

Fehlerverhalten: Fehlen Eingangsdaten, wird der letzte Wert zunächst gehalten
(Status ``waiting``). Dauert das länger als ``fault_timeout_min``, wird der Sensor
``unavailable`` (Status ``fault``) und die Anlage fällt auf ihren eigenen Innensensor
zurück. Ist der Regler aus oder die Anlage nicht im Heizbetrieb, ist der Sensor
sofort ``unavailable``.
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
    CONF_FACTOR_DOWN,
    CONF_FACTOR_FLOOR,
    CONF_FACTOR_MAX,
    CONF_FACTOR_MIN,
    CONF_FACTOR_UP,
    CONF_FAULT_TIMEOUT,
    CONF_FREQUENCY,
    CONF_HOLD_LIMIT,
    CONF_HUNTING,
    CONF_INTERVAL,
    CONF_MAX_OFFSET,
    CONF_OFFSET_BRAKE,
    CONF_OFFSET_LOWER,
    CONF_OFFSET_RAISE,
    CONF_STEP_NORMAL,
    CONF_STEP_RAISE,
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
from .regelung import Params, State, step

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

        # Regelkern-Zustand
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
            deadband_hz=float(c[CONF_DEADBAND]),
            offset_raise=float(c[CONF_OFFSET_RAISE]),
            offset_lower=float(c[CONF_OFFSET_LOWER]),
            offset_brake=float(c[CONF_OFFSET_BRAKE]),
            hold_limit=float(c[CONF_HOLD_LIMIT]),
            step_raise=float(c[CONF_STEP_RAISE]),
            step_normal=float(c[CONF_STEP_NORMAL]),
            max_offset=float(c[CONF_MAX_OFFSET]),
            hunting_hz=float(c[CONF_HUNTING]),
            factor_min=float(c[CONF_FACTOR_MIN]),
            factor_max=float(c[CONF_FACTOR_MAX]),
            factor_floor=float(c[CONF_FACTOR_FLOOR]),
            factor_down=float(c[CONF_FACTOR_DOWN]),
            factor_up=float(c[CONF_FACTOR_UP]),
        )

    # ------------------------------------------------------------------ Lebenszyklus
    async def async_load(self) -> None:
        """Gespeicherten Zustand laden."""
        data = await self._store.async_load() or {}
        self.enabled = bool(data.get("enabled", False))
        target = _to_float(data.get("target_hz"))
        brake = _to_float(data.get("brake_hz"))
        factor = _to_float(data.get("factor"))
        output = _to_float(data.get("output"))
        if target is not None:
            self.target_hz = min(max(target, TARGET_HZ_MIN), TARGET_HZ_MAX)
        if brake is not None:
            self.brake_hz = min(max(brake, BRAKE_HZ_MIN), BRAKE_HZ_MAX)
        if factor is not None:
            self.regelung.factor = factor
        self.regelung.output = output

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
            "factor": self.regelung.factor,
            "output": self.regelung.output,
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
        """Lernfaktor auf 1,0 und Frequenz-Historie löschen."""
        self.regelung.factor = 1.0
        self.regelung.hz_prev1 = self.regelung.hz_prev2 = None
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
            self._set_inactive(STATUS_OFF)
            return

        climate = self.hass.states.get(cfg[CONF_CLIMATE])
        climate_ok = climate is not None and climate.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )
        if climate_ok and climate.state != HVAC_MODE_ACTIVE:
            # Anlage aus / kühlt / ... -> Sensor sofort weg, Anlage nutzt ihren eigenen
            self._set_inactive(STATUS_IDLE)
            return

        setpoint = _to_float(climate.attributes.get("temperature")) if climate_ok else None
        freq = self.hass.states.get(cfg[CONF_FREQUENCY])
        hz = _to_float(freq.state) if freq is not None else None
        if setpoint is None or hz is None:
            self._handle_missing_data()
            return

        self._fault_since = None
        result = step(self.params, self.regelung, setpoint, hz, self.target_hz, self.brake_hz)
        self.available = True
        self.output = result.published
        self.offset = result.offset
        self.error_hz = result.error_hz
        self.status = result.mode
        _LOGGER.debug(
            "Takt: soll=%.1f hz=%.1f ziel=%.0f -> %s, sensor=%.1f (offset %.2f, faktor %.2f)",
            setpoint,
            hz,
            min(self.target_hz, self.brake_hz),
            result.mode,
            result.published,
            result.offset,
            result.factor,
        )

    def _set_inactive(self, status: str) -> None:
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
            self.output = self.offset = self.error_hz = None
            self.status = STATUS_FAULT
            self.regelung.hz_prev1 = self.regelung.hz_prev2 = None
        else:
            self.status = STATUS_WAITING
