"""Regelkern: Kompressor-Frequenz über einen vorgetäuschten Raumtemperatursensor einpendeln.

Reine Logik ohne Home-Assistant-Abhängigkeit, damit sie sich einzeln testen lässt.

Die Berechnung ist eine 1:1-Portierung der bewährten YAML-Regelung (klima_srk35_auto.yaml,
Version 8.1) für den **Heizbetrieb**:

* Fehler in Hz:            err = ziel - hz
* Stellgröße:              Sensorwert = Soll - Offset   (Offset > 0  ->  Anlage hält Raum für kälter
                                                         ->  mehr Frequenz)
* Totband (±deadband_hz):  Der letzte Offset wird gehalten (begrenzt auf ±hold_limit).
* Zu wenig Hz:             Offset +offset_raise, langsam (step_raise je Minute).
* Zu viel Hz:              Offset -offset_lower, sofort.
* Notbremse:               hz > brake_hz -> Offset -offset_brake.
* Lernfaktor:              skaliert den Offset; sinkt bei Pendeln, steigt im Totband.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def round1(value: float) -> float:
    """Kaufmännisch auf 0,1 runden (nicht Banker's rounding)."""
    return math.floor(value * 10 + 0.5) / 10


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# Reglerzustände (werden auch als Status-Sensor ausgegeben)
MODE_RAISE = "raise"  # Frequenz zu niedrig -> Sensor wird kälter
MODE_LOWER = "lower"  # Frequenz zu hoch   -> Sensor wird wärmer
MODE_HOLD = "hold"  # im Totband         -> letzten Offset halten
MODE_BRAKE = "brake"  # Notbremse


@dataclass(frozen=True)
class Params:
    """Alle einstellbaren Zahlen der Regelung (Standardwerte = deine YAML)."""

    interval_s: float = 60.0  # Regeltakt; Schrittweiten gelten je 60 s und werden skaliert
    deadband_hz: float = 3.0  # Totband um die Ziel-Frequenz
    offset_raise: float = 0.6  # K, Frequenz zu niedrig
    offset_lower: float = 0.4  # K, Frequenz zu hoch (wirkt als negativer Offset)
    offset_brake: float = 0.5  # K, Notbremse (wirkt als negativer Offset)
    hold_limit: float = 0.3  # K, Begrenzung des gehaltenen Offsets im Totband
    step_raise: float = 0.1  # K je Minute, wenn Frequenz zu niedrig
    step_normal: float = 0.08  # K je Minute, sonst
    max_offset: float = 1.0  # K, Sicherheitsgrenze: Sensor bleibt in Soll ± max_offset
    hunting_hz: float = 2.0  # Hz-Sprung je Takt, ab dem Pendeln erkannt wird
    factor_min: float = 0.6
    factor_max: float = 1.2
    factor_floor: float = 0.8  # Wert, auf den der Faktor außerhalb des Totbands zurückkehrt
    factor_down: float = 0.1  # Absenkung bei Pendeln
    factor_up: float = 0.05  # Anhebung im Totband


@dataclass
class State:
    """Gedächtnis des Reglers (wird teilweise über Neustarts gespeichert)."""

    factor: float = 1.0
    output: float | None = None  # letzter Sensorwert (ungerundet, 2 Nachkommastellen)
    hz_prev1: float | None = None
    hz_prev2: float | None = None


@dataclass(frozen=True)
class Result:
    """Ergebnis eines Regelschritts."""

    output: float  # exakter interner Wert
    published: float  # auf 0,1 gerundeter Wert für den Sensor
    offset: float  # Soll - Sensorwert (K), positiv = Anlage wird zum Heizen "angeschoben"
    error_hz: float  # ziel - hz
    mode: str
    hunting: bool
    factor: float  # neuer Lernfaktor


def step(
    p: Params,
    s: State,
    setpoint: float,
    hz: float,
    target_hz: float,
    brake_hz: float,
) -> Result:
    """Ein Regelschritt. Verändert ``s`` und gibt das Ergebnis zurück."""
    ziel = min(target_hz, brake_hz)
    err = ziel - hz

    # --- Pendel-Erkennung & Lernfaktor -------------------------------------------------
    hz_v1 = s.hz_prev1 if s.hz_prev1 is not None else hz
    hz_v2 = s.hz_prev2 if s.hz_prev2 is not None else hz_v1
    trend = hz - hz_v1
    hunting = trend * (hz_v1 - hz_v2) < 0 and abs(trend) > p.hunting_hz

    factor = s.factor
    if hunting:
        new_factor = max(p.factor_min, factor - p.factor_down)
    elif abs(err) <= p.deadband_hz:
        new_factor = min(p.factor_max, factor + p.factor_up)
    else:
        new_factor = max(p.factor_floor, factor)
    new_factor = round(_clamp(new_factor, p.factor_min, p.factor_max), 2)

    # --- Gewünschter Offset ----------------------------------------------------------
    low, high = setpoint - p.max_offset, setpoint + p.max_offset
    v_alt = s.output if s.output is not None else setpoint
    v_alt = _clamp(v_alt, low, high)
    d_alt = setpoint - v_alt

    if hz > brake_hz:
        mode, d_raw = MODE_BRAKE, -p.offset_brake
    elif err > p.deadband_hz:
        mode, d_raw = MODE_RAISE, p.offset_raise
    elif err < -p.deadband_hz:
        mode, d_raw = MODE_LOWER, -p.offset_lower
    else:
        mode, d_raw = MODE_HOLD, _clamp(d_alt, -p.hold_limit, p.hold_limit)

    # Der Faktor des *bisherigen* Taktes skaliert den Offset (wie in der YAML)
    d_calc = round(d_raw * factor, 2)
    v_target = _clamp(round1(setpoint - d_calc), low, high)

    # --- Schrittbegrenzung ------------------------------------------------------------
    scale = p.interval_s / 60.0
    v_delta_max = (p.step_raise if err > p.deadband_hz else p.step_normal) * scale
    diff = v_target - v_alt
    if err < -p.deadband_hz:
        v_cmd = v_target  # zu viel Hz: sofort
    elif diff > v_delta_max:
        v_cmd = round(v_alt + v_delta_max, 2)
    elif diff < -v_delta_max:
        v_cmd = round(v_alt - v_delta_max, 2)
    else:
        v_cmd = v_target

    # --- Zustand fortschreiben --------------------------------------------------------
    s.factor = new_factor
    s.output = v_cmd
    s.hz_prev2 = hz_v1
    s.hz_prev1 = hz

    return Result(
        output=v_cmd,
        published=round1(v_cmd),
        offset=round(setpoint - v_cmd, 2),
        error_hz=round(err, 1),
        mode=mode,
        hunting=hunting,
        factor=new_factor,
    )
