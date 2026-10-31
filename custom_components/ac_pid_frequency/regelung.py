"""Intelligenter Regelkern: Kompressor-Frequenz über vorgetäuschten Raumsensor einpendeln.

Reine Logik ohne Home-Assistant-Abhängigkeit, vollständig testbar.

Besonderheiten dieses Algorithmus:
* Totzeit-Entkopplung (Patience-Timer): Respektiert die Ansprechzeit der Klimaanlage (z. B. 120 s).
  Solange die Frequenz bereits in die gewünschte Richtung dreht, wird nicht vorzeitig nachgelegt.
* 2D-Arbeitspunkt-Lernen: Lernt für verschiedene Außentemperaturzonen (Frost, Übergang, Mild)
  und Ziel-Frequenzbereiche den passenden Grund-Offset und speichert ihn dauerhaft.
* Überschwinger-Dämpfung: Schießt die Frequenz über das Ziel hinaus, wird der gelernte
  Offset für diesen Bereich automatisch verringert.
* Abtau-Pause (Defrost): Friert Stellgröße und Lernen ein, verhindert Fehlauslösung der Notbremse.
* Thermischer Überhitzungsschutz: Drosselt die Frequenz, wenn der echte Raum zu warm wird.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field


def round1(value: float) -> float:
    """Kaufmännisch auf 0,1 runden (nicht Banker's rounding)."""
    return math.floor(value * 10 + 0.5) / 10


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# Reglerzustände
MODE_RAISE = "raise"        # Frequenz zu niedrig -> Sensor schrittweise kälter
MODE_LOWER = "lower"        # Frequenz zu hoch -> Sensor wärmer
MODE_HOLD = "hold"          # Im Totband -> stabil halten & lernen
MODE_BRAKE = "brake"        # Frequenz-Notbremse aktiv
MODE_DEFROST = "defrost"    # Abtauung / Vorheizen aktiv -> pausiert
MODE_OVERHEAT = "overheat"  # Raum überhitzt -> thermische Notbremse aktiv

# Außentemperatur-Bins
OUTDOOR_BIN_COLD = "cold"      # < 2 °C (Frost / Winter)
OUTDOOR_BIN_NORMAL = "normal"  # 2 .. 10 °C (Übergang)
OUTDOOR_BIN_WARM = "warm"      # > 10 °C (Mild)
OUTDOOR_BIN_NONE = "none"      # kein Außensensor verfügbar

OUTDOOR_BINS = [OUTDOOR_BIN_COLD, OUTDOOR_BIN_NORMAL, OUTDOOR_BIN_WARM, OUTDOOR_BIN_NONE]

# Frequenz-Bins
FREQ_BIN_LOW = "low"            # < 28 Hz
FREQ_BIN_MID_LOW = "mid_low"    # 28 .. 38 Hz
FREQ_BIN_MID_HIGH = "mid_high"  # 38 .. 50 Hz
FREQ_BIN_HIGH = "high"          # >= 50 Hz

FREQ_BINS = [FREQ_BIN_LOW, FREQ_BIN_MID_LOW, FREQ_BIN_MID_HIGH, FREQ_BIN_HIGH]

# Standard-Offsets (K) je (Outdoor-Bin, Freq-Bin):
DEFAULT_LEARNED_OFFSETS: dict[str, dict[str, float]] = {
    OUTDOOR_BIN_COLD: {
        FREQ_BIN_LOW: 0.25,
        FREQ_BIN_MID_LOW: 0.45,
        FREQ_BIN_MID_HIGH: 0.65,
        FREQ_BIN_HIGH: 0.85,
    },
    OUTDOOR_BIN_NORMAL: {
        FREQ_BIN_LOW: 0.15,
        FREQ_BIN_MID_LOW: 0.35,
        FREQ_BIN_MID_HIGH: 0.50,
        FREQ_BIN_HIGH: 0.70,
    },
    OUTDOOR_BIN_WARM: {
        FREQ_BIN_LOW: 0.10,
        FREQ_BIN_MID_LOW: 0.25,
        FREQ_BIN_MID_HIGH: 0.40,
        FREQ_BIN_HIGH: 0.55,
    },
    OUTDOOR_BIN_NONE: {
        FREQ_BIN_LOW: 0.15,
        FREQ_BIN_MID_LOW: 0.35,
        FREQ_BIN_MID_HIGH: 0.50,
        FREQ_BIN_HIGH: 0.70,
    },
}


def get_outdoor_bin(temp: float | None) -> str:
    """Ermittelt den Außentemperaturbereich."""
    if temp is None:
        return OUTDOOR_BIN_NONE
    if temp < 2.0:
        return OUTDOOR_BIN_COLD
    if temp <= 10.0:
        return OUTDOOR_BIN_NORMAL
    return OUTDOOR_BIN_WARM


def get_freq_bin(target_hz: float) -> str:
    """Ermittelt den Frequenzbereich."""
    if target_hz < 28.0:
        return FREQ_BIN_LOW
    if target_hz < 38.0:
        return FREQ_BIN_MID_LOW
    if target_hz < 50.0:
        return FREQ_BIN_MID_HIGH
    return FREQ_BIN_HIGH


@dataclass(frozen=True)
class Params:
    """Regel- und Lernparameter."""

    interval_s: float = 60.0          # Regeltakt in Sekunden
    reaction_time_s: float = 120.0    # Mindest-Beobachtungszeit der Anlage nach einem Schritt
    deadband_hz: float = 3.0          # Totband um die Ziel-Frequenz (Hz)
    offset_brake: float = 0.5         # K, Frequenz-Notbremse (Sensor wird wärmer als Soll)
    max_offset: float = 1.0           # K, Sicherheitsgrenze: Sensor bleibt in Soll ± max_offset
    max_room_overheat: float = 1.0    # K, maximale Raumüberhitzung über Soll vor thermischer Drosselung
    learning_rate: float = 0.15       # Exponentielle Glättung beim Lernen im Totband
    overshoot_penalty: float = 0.05   # K, Reduktion des gelernten Offsets bei Überschwingern


@dataclass
class State:
    """Gedächtnis des Reglers (wird über Neustarts gespeichert)."""

    output: float | None = None
    time_since_last_step: float = 0.0
    stable_cycles: int = 0
    overshoot_detected: bool = False
    last_target_hz: float | None = None
    hz_prev1: float | None = None
    hz_prev2: float | None = None
    current_outdoor_bin: str = OUTDOOR_BIN_NONE
    current_freq_bin: str = FREQ_BIN_MID_LOW
    current_learned_offset: float = 0.35
    learned_table: dict[str, dict[str, float]] = field(
        default_factory=lambda: copy.deepcopy(DEFAULT_LEARNED_OFFSETS)
    )

    def reset_learning(self) -> None:
        """Setzt die gelernten Tabellen auf Standardwerte zurück."""
        self.learned_table = copy.deepcopy(DEFAULT_LEARNED_OFFSETS)
        self.stable_cycles = 0
        self.overshoot_detected = False

    def load_learned_table(self, data: dict) -> None:
        """Lädt eine gespeicherte Lerntabelle sicher."""
        for obin in OUTDOOR_BINS:
            if obin in data and isinstance(data[obin], dict):
                for fbin in FREQ_BINS:
                    if fbin in data[obin]:
                        try:
                            val = float(data[obin][fbin])
                            self.learned_table[obin][fbin] = round(val, 2)
                        except (ValueError, TypeError):
                            pass


@dataclass(frozen=True)
class Result:
    """Ergebnis eines Regelschritts."""

    output: float            # Interner Wert
    published: float         # Gerundet auf 0,1 K für den Home-Assistant-Sensor
    offset: float            # Soll minus Ausgabewert (K, positiv = heizen)
    error_hz: float          # ziel_hz minus ist_hz
    mode: str                # raise / lower / hold / brake / defrost / overheat
    outdoor_bin: str         # Aktive Außentemperaturzone
    freq_bin: str            # Aktiver Frequenzbereich
    learned_offset: float    # Aktueller Erfahrungswert (K) für diesen Arbeitspunkt


def step(
    p: Params,
    s: State,
    setpoint: float,
    hz: float,
    target_hz: float,
    brake_hz: float,
    outdoor_temp: float | None = None,
    room_temp: float | None = None,
    defrost: bool = False,
) -> Result:
    """Führt einen Regelschritt aus."""
    s.time_since_last_step += p.interval_s
    ziel = min(target_hz, brake_hz)
    err = ziel - hz

    outdoor_bin = get_outdoor_bin(outdoor_temp)
    freq_bin = get_freq_bin(ziel)
    s.current_outdoor_bin = outdoor_bin
    s.current_freq_bin = freq_bin

    learned_offset = s.learned_table[outdoor_bin][freq_bin]
    s.current_learned_offset = learned_offset

    # Zielwert-Änderung erkennen -> sofortige Reaktion erlauben
    if s.last_target_hz is not None and abs(ziel - s.last_target_hz) > 1.0:
        s.stable_cycles = 0
        s.overshoot_detected = False
        s.time_since_last_step = p.reaction_time_s
    s.last_target_hz = ziel

    # Frequenz-Verlauf & Trend (Hz-Änderung pro Takt)
    hz_v1 = s.hz_prev1 if s.hz_prev1 is not None else hz
    trend = hz - hz_v1

    low, high = setpoint - p.max_offset, setpoint + p.max_offset

    # ------------------------------------------------------------------ 1. ABTAUUNG
    if defrost:
        v_out = s.output if s.output is not None else setpoint
        v_out = _clamp(v_out, low, high)
        s.hz_prev2 = hz_v1
        s.hz_prev1 = hz
        s.stable_cycles = 0
        s.overshoot_detected = False
        return Result(
            output=v_out,
            published=round1(v_out),
            offset=round(setpoint - v_out, 2),
            error_hz=round(err, 1),
            mode=MODE_DEFROST,
            outdoor_bin=outdoor_bin,
            freq_bin=freq_bin,
            learned_offset=learned_offset,
        )

    # ------------------------------------------------------------------ 2. RAUM-ÜBERHITZUNGSSCHUTZ
    if room_temp is not None and room_temp >= (setpoint + p.max_room_overheat):
        v_out = _clamp(setpoint + 0.4, low, high)
        s.output = v_out
        s.time_since_last_step = 0.0
        s.stable_cycles = 0
        s.hz_prev2 = hz_v1
        s.hz_prev1 = hz
        return Result(
            output=v_out,
            published=round1(v_out),
            offset=round(setpoint - v_out, 2),
            error_hz=round(err, 1),
            mode=MODE_OVERHEAT,
            outdoor_bin=outdoor_bin,
            freq_bin=freq_bin,
            learned_offset=learned_offset,
        )

    # ------------------------------------------------------------------ 3. NOTBREMSE KOMPRESSOR
    if hz > brake_hz:
        v_out = _clamp(setpoint + p.offset_brake, low, high)
        s.output = v_out
        s.time_since_last_step = 0.0
        s.stable_cycles = 0
        if not s.overshoot_detected:
            s.overshoot_detected = True
            new_learned = max(0.05, learned_offset - p.overshoot_penalty)
            s.learned_table[outdoor_bin][freq_bin] = round(new_learned, 2)
            s.current_learned_offset = round(new_learned, 2)
        s.hz_prev2 = hz_v1
        s.hz_prev1 = hz
        return Result(
            output=v_out,
            published=round1(v_out),
            offset=round(setpoint - v_out, 2),
            error_hz=round(err, 1),
            mode=MODE_BRAKE,
            outdoor_bin=outdoor_bin,
            freq_bin=freq_bin,
            learned_offset=s.current_learned_offset,
        )

    # ------------------------------------------------------------------ 4. NORMALE REGELUNG
    # Wenn noch kein Wert vorhanden ist, starten wir sanft beim gelernten Arbeitspunkt
    if s.output is None:
        v_alt = _clamp(round1(setpoint - learned_offset), low, high)
        s.output = v_alt
        s.time_since_last_step = 0.0
    else:
        v_alt = _clamp(s.output, low, high)

    current_offset = round(setpoint - v_alt, 2)

    # Fall A: Im Totband (Ziel erreicht)
    if abs(err) <= p.deadband_hz:
        mode = MODE_HOLD
        v_cmd = v_alt
        s.stable_cycles += 1
        s.overshoot_detected = False

        # Wenn die Frequenz mindestens 2 Takte im Totband stabil ist:
        # Erfahrungswert für diesen Arbeitspunkt mit exponentieller Glättung aktualisieren
        if s.stable_cycles >= 2 and current_offset > 0:
            new_learned = (1.0 - p.learning_rate) * learned_offset + p.learning_rate * current_offset
            new_learned = round(_clamp(new_learned, 0.05, p.max_offset), 2)
            s.learned_table[outdoor_bin][freq_bin] = new_learned
            s.current_learned_offset = new_learned

    # Fall B: Zu viel Frequenz (err < -deadband)
    elif err < -p.deadband_hz:
        mode = MODE_LOWER
        s.stable_cycles = 0

        # Überschwinger erkennen (mind. 2 Hz über Totband hinaus geschossen)
        if err < -(p.deadband_hz + 2.0) and not s.overshoot_detected:
            s.overshoot_detected = True
            new_learned = max(0.05, learned_offset - p.overshoot_penalty)
            s.learned_table[outdoor_bin][freq_bin] = round(new_learned, 2)
            s.current_learned_offset = round(new_learned, 2)

        # Fällt die Frequenz bereits zügig ab, halten wir still
        if trend < -2.0:
            v_cmd = v_alt
        elif s.time_since_last_step >= (p.reaction_time_s / 2.0):
            # Schrittweise wärmer stellen (Sensor anheben)
            v_cmd = round1(v_alt + 0.1)
            s.time_since_last_step = 0.0
        else:
            v_cmd = v_alt

    # Fall C: Zu wenig Frequenz (err > deadband)
    else:
        mode = MODE_RAISE
        s.stable_cycles = 0

        # Wenn der Kompressor bereits aktiv nach oben beschleunigt (Trend positiv):
        # Geduldig abwarten und nicht vorzeitig nachlegen!
        if trend >= 1.5:
            v_cmd = v_alt
        elif s.time_since_last_step >= p.reaction_time_s:
            # Reaktionszeit verstrichen und Frequenz stagniert noch unter Ziel:
            # Behutsamen Schritt um 0,1 K nach unten (kälter) machen
            v_cmd = round1(v_alt - 0.1)
            s.time_since_last_step = 0.0
        else:
            v_cmd = v_alt

    v_cmd = _clamp(v_cmd, low, high)
    s.output = v_cmd
    s.hz_prev2 = hz_v1
    s.hz_prev1 = hz

    return Result(
        output=v_cmd,
        published=round1(v_cmd),
        offset=round(setpoint - v_cmd, 2),
        error_hz=round(err, 1),
        mode=mode,
        outdoor_bin=outdoor_bin,
        freq_bin=freq_bin,
        learned_offset=s.current_learned_offset,
    )
