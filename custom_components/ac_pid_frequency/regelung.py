"""Intelligenter, selbstlernender Regelkern für AC PID Frequency.

Reine Logik ohne Home-Assistant-Abhängigkeit, vollständig testbar.

Besonderheiten dieses Algorithmus:
* Adaptive Totzeit & Reaktionszeit: Lernt dynamisch die Ansprechzeit (z. B. 60–180 s)
  und Verstärkung (Hz/K) der Klimaanlage aus ihren echten Sprungantworten.
* Momentum-Erkennung (Trend): Bewegt sich die Frequenz bereits mit genügend Dynamik
  in Richtung Ziel, wird geduldig abgewartet statt vorzeitig nachzulegen.
* Automatische Mindestmodulations-Erkennung & Abschaltschutz:
  Liegt die Soll-Hz unterhalb der physikalisch erreichbaren Mindestmodulation (oder droht
  die Anlage auszugehen), lernt der Algorithmus die Minimalfrequenz und den nötigen
  Halte-Offset. Die Anlage wird stabil auf der Mindestmodulation gehalten und schaltet
  nicht mehr aus ("Takten" wird verhindert).
* Vollständige Defrost- & Erholungsphasen-Behandlung:
  Während der Abtauung und in einer anschließenden Nach-Abtau-Stabilisierungsphase
  (120 s) pausieren Regelung und Trendberechnung vollständig.
* Wetterabhängiges 2D-Arbeitspunkt-Lernen:
  Lernt für Außentemperaturzonen (Frost, Übergang, Mild) und Frequenzbereiche kontinuierlich
  den passenden Grund-Offset und speichert ihn dauerhaft.
* Thermischer Überhitzungsschutz:
  Drosselt die Frequenz sanft, wenn der reale Raum zu warm wird.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field


def round1(value: float) -> float:
    """Kaufmännisch auf 0,1 runden (nicht Banker's rounding)."""
    return math.floor(value * 10.0 + 0.5) / 10.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# Reglerzustände
MODE_RAISE = "raise"        # Frequenz zu niedrig -> Sensor schrittweise kälter
MODE_LOWER = "lower"        # Frequenz zu hoch -> Sensor wärmer
MODE_HOLD = "hold"          # Im Totband -> stabil halten & lernen
MODE_MIN_MOD = "min_mod"    # Ziel unter Mindestmodulation -> stabil auf Minimum halten
MODE_DEFROST = "defrost"    # Abtauung / Nach-Abtau-Phase -> pausiert
MODE_OVERHEAT = "overheat"  # Raum überhitzt -> thermischer Schutz aktiv

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
    """Minimale Regelparameter (auf das Notwendige reduziert)."""

    interval_s: float = 60.0          # Regeltakt in Sekunden
    max_offset: float = 2.0           # K, Sicherheitsgrenze: Sensor bleibt in Soll ± max_offset
    max_room_overheat: float = 1.0    # K, maximale Raumüberhitzung über Soll vor thermischer Drosselung
    deadband_hz: float = 2.0          # Hz, Totband um Ziel-Frequenz
    learning_rate: float = 0.15       # Exponentielle Glättung beim Lernen im Totband


@dataclass
class State:
    """Gedächtnis und dynamischer Lernzustand des Reglers (persistent)."""

    output: float | None = None
    time_since_last_step: float = 0.0
    stable_cycles: int = 0
    last_target_hz: float | None = None
    hz_prev1: float | None = None
    hz_prev2: float | None = None
    trend: float = 0.0
    current_outdoor_bin: str = OUTDOOR_BIN_NONE
    current_freq_bin: str = FREQ_BIN_MID_LOW
    current_learned_offset: float = 0.35
    learned_table: dict[str, dict[str, float]] = field(
        default_factory=lambda: copy.deepcopy(DEFAULT_LEARNED_OFFSETS)
    )

    # --- Selbstlernende Anlagendynamik ---
    learned_min_hz: float = 15.0       # Erlernte Mindestmodulation (Hz)
    learned_min_offset: float = 0.15   # Erlernter Offset für Mindestmodulation (K)
    learned_reaction_time: float = 90.0 # Erlernte Reaktionszeit (s)
    learned_sensitivity: float = 15.0   # Erlernte Verstärkung (Hz je Kelvin)

    # Schrittbeobachtung
    last_step_delta: float = 0.0
    hz_at_last_step: float | None = None

    # Abtau-Status
    was_defrosting: bool = False
    post_defrost_remaining: float = 0.0

    # Beobachtungen vor Abschaltung / Stagnation
    last_running_hz: float | None = None
    low_hz_stagnation_count: int = 0
    effective_target_hz: float = 30.0

    def reset_learning(self) -> None:
        """Setzt gelernte Tabellen und Anlageneigenschaften auf Werkseinstellungen zurück."""
        self.learned_table = copy.deepcopy(DEFAULT_LEARNED_OFFSETS)
        self.learned_min_hz = 15.0
        self.learned_min_offset = 0.15
        self.learned_reaction_time = 90.0
        self.learned_sensitivity = 15.0
        self.stable_cycles = 0
        self.last_step_delta = 0.0
        self.hz_at_last_step = None
        self.low_hz_stagnation_count = 0
        self.last_running_hz = None

    def load_learned_data(self, data: dict) -> None:
        """Lädt gespeicherte Lerndaten sicher."""
        if not isinstance(data, dict):
            return

        table = data.get("learned_table")
        if isinstance(table, dict):
            for obin in OUTDOOR_BINS:
                if obin in table and isinstance(table[obin], dict):
                    for fbin in FREQ_BINS:
                        if fbin in table[obin]:
                            try:
                                val = float(table[obin][fbin])
                                self.learned_table[obin][fbin] = round(val, 2)
                            except (ValueError, TypeError):
                                pass

        for key, attr, low, high in [
            ("learned_min_hz", "learned_min_hz", 10.0, 60.0),
            ("learned_min_offset", "learned_min_offset", 0.05, 2.0),
            ("learned_reaction_time", "learned_reaction_time", 30.0, 300.0),
            ("learned_sensitivity", "learned_sensitivity", 5.0, 50.0),
        ]:
            if key in data:
                try:
                    val = float(data[key])
                    setattr(self, attr, _clamp(val, low, high))
                except (ValueError, TypeError):
                    pass

    def export_learned_data(self) -> dict:
        """Exportiert alle gelernten Kennwerte für die dauerhafte Speicherung."""
        return {
            "learned_table": self.learned_table,
            "learned_min_hz": round(self.learned_min_hz, 1),
            "learned_min_offset": round(self.learned_min_offset, 2),
            "learned_reaction_time": round(self.learned_reaction_time, 1),
            "learned_sensitivity": round(self.learned_sensitivity, 1),
        }


@dataclass(frozen=True)
class Result:
    """Ergebnis eines Regelschritts."""

    output: float            # Interner Wert
    published: float         # Gerundet auf 0,1 K für den Home-Assistant-Sensor
    offset: float            # Soll minus Ausgabewert (K, positiv = heizen)
    error_hz: float          # ziel_hz minus ist_hz
    mode: str                # raise / lower / hold / min_mod / defrost / overheat
    outdoor_bin: str         # Aktive Außentemperaturzone
    freq_bin: str            # Aktiver Frequenzbereich
    learned_offset: float    # Aktueller Erfahrungswert (K) für diesen Arbeitspunkt
    effective_target_hz: float  # Tatsächlich angesteuerte Ziel-Frequenz (geclampt an min_hz)
    learned_min_hz: float    # Aktuell gelernte Mindestmodulation


def step(
    p: Params,
    s: State,
    setpoint: float,
    hz: float,
    target_hz: float,
    outdoor_temp: float | None = None,
    room_temp: float | None = None,
    defrost: bool = False,
) -> Result:
    """Führt einen intelligenten, selbstlernenden Regelschritt aus."""
    s.time_since_last_step += p.interval_s

    outdoor_bin = get_outdoor_bin(outdoor_temp)
    s.current_outdoor_bin = outdoor_bin

    low = setpoint - p.max_offset
    high = setpoint + p.max_offset

    # ==================================================================
    # 1. ABTAUUNG & POST-DEFROST STABILISIERUNG
    # ==================================================================
    if defrost:
        s.was_defrosting = True
        s.time_since_last_step = 0.0
        s.stable_cycles = 0
        s.hz_prev1 = s.hz_prev2 = None
        s.trend = 0.0
        s.last_step_delta = 0.0
        v_out = s.output if s.output is not None else setpoint
        v_out = _clamp(v_out, low, high)
        freq_bin = get_freq_bin(target_hz)
        s.current_freq_bin = freq_bin
        learned_offset = s.learned_table[outdoor_bin][freq_bin]
        s.current_learned_offset = learned_offset
        return Result(
            output=v_out,
            published=round1(v_out),
            offset=round(setpoint - v_out, 2),
            error_hz=round(target_hz - hz, 1),
            mode=MODE_DEFROST,
            outdoor_bin=outdoor_bin,
            freq_bin=freq_bin,
            learned_offset=learned_offset,
            effective_target_hz=target_hz,
            learned_min_hz=s.learned_min_hz,
        )

    if s.was_defrosting:
        # Abtauung gerade beendet -> 120s Schonzeit für Druckausgleich und Anlauf
        s.was_defrosting = False
        s.post_defrost_remaining = 120.0
        s.time_since_last_step = 0.0
        s.hz_prev1 = s.hz_prev2 = None
        s.trend = 0.0

    if s.post_defrost_remaining > 0:
        s.post_defrost_remaining = max(0.0, s.post_defrost_remaining - p.interval_s)
        s.time_since_last_step = 0.0
        s.stable_cycles = 0
        v_out = s.output if s.output is not None else setpoint
        v_out = _clamp(v_out, low, high)
        freq_bin = get_freq_bin(target_hz)
        s.current_freq_bin = freq_bin
        learned_offset = s.learned_table[outdoor_bin][freq_bin]
        return Result(
            output=v_out,
            published=round1(v_out),
            offset=round(setpoint - v_out, 2),
            error_hz=round(target_hz - hz, 1),
            mode=MODE_DEFROST,
            outdoor_bin=outdoor_bin,
            freq_bin=freq_bin,
            learned_offset=learned_offset,
            effective_target_hz=target_hz,
            learned_min_hz=s.learned_min_hz,
        )

    # ==================================================================
    # 2. KOMPRESSOR-ABSCHALT-ERKENNUNG & MINDESTMODULATION LERNEN
    # ==================================================================
    compressor_off = hz <= 1.0

    if compressor_off:
        # Die Anlage ist ausgegangen! War das die Folge eines Ziels unter Mindestmodulation?
        if (
            s.last_running_hz is not None
            and s.last_running_hz > 10.0
            and s.last_target_hz is not None
            and s.last_target_hz <= s.last_running_hz
        ):
            # Der Kompressor lief zuletzt stabil bei last_running_hz und ging beim Versuch
            # weiter abzusenken aus. Die Mindestmodulation ist damit exakt identifiziert!
            s.learned_min_hz = max(s.learned_min_hz, round(s.last_running_hz, 1))
            # Halte-Offset für Mindestmodulation sichern (etwas kälter als Aus-Punkt)
            s.learned_min_offset = max(0.15, s.current_learned_offset)

        # Kompressor sofort durch ausreichenden Kälte-Offset wieder anschieben
        restart_offset = max(0.25, s.learned_min_offset)
        v_cmd = round1(setpoint - restart_offset)
        s.output = _clamp(v_cmd, low, high)
        s.time_since_last_step = 0.0
        s.stable_cycles = 0
        s.hz_prev1 = s.hz_prev2 = None
        s.trend = 0.0
        s.last_step_delta = 0.0
        s.last_running_hz = None

        freq_bin = get_freq_bin(target_hz)
        return Result(
            output=s.output,
            published=round1(s.output),
            offset=round(setpoint - s.output, 2),
            error_hz=round(target_hz - hz, 1),
            mode=MODE_RAISE,
            outdoor_bin=outdoor_bin,
            freq_bin=freq_bin,
            learned_offset=s.current_learned_offset,
            effective_target_hz=max(target_hz, s.learned_min_hz),
            learned_min_hz=s.learned_min_hz,
        )

    # Kompressor läuft: aktuellen Wert als letzten laufenden Zustand merken
    s.last_running_hz = hz

    # ==================================================================
    # 3. EFFEKTIVE ZIEL-FREQUENZ (MINDESTMODULATIONS-SCHUTZ)
    # ==================================================================
    # Wenn target_hz unterhalb der erlernten Mindestmodulation liegt, kappen wir
    # das Ziel auf die Mindestmodulation, damit die Anlage NIE MEHR ausgeht!
    target_below_min = target_hz < s.learned_min_hz
    effective_target = max(s.learned_min_hz, target_hz)
    s.effective_target_hz = effective_target

    freq_bin = get_freq_bin(effective_target)
    s.current_freq_bin = freq_bin

    learned_offset = s.learned_table[outdoor_bin][freq_bin]
    s.current_learned_offset = learned_offset

    # Zielwert-Änderung erkennen -> sofortige Reaktionszeit erlauben
    if s.last_target_hz is not None and abs(effective_target - s.last_target_hz) > 1.0:
        s.stable_cycles = 0
        s.low_hz_stagnation_count = 0
        s.time_since_last_step = s.learned_reaction_time
    s.last_target_hz = effective_target

    # ==================================================================
    # 4. TREND-BERECHNUNG & DYNAMISCHES LERNEN DER ANSPRECHZEIT
    # ==================================================================
    hz_v1 = s.hz_prev1 if s.hz_prev1 is not None else hz
    delta_hz_raw = hz - hz_v1
    time_factor = 60.0 / max(5.0, p.interval_s)
    trend_raw = delta_hz_raw * time_factor  # Hz je Minute

    # Glättung des Trends
    s.trend = 0.6 * s.trend + 0.4 * trend_raw

    # Dynamisches Lernen der Reaktionszeit und Verstärkung aus der letzten Stufe
    if s.last_step_delta != 0.0 and s.hz_at_last_step is not None:
        # Hat sich die Frequenz nach dem Schritt beruhigt (Plateau erreicht)?
        if (abs(trend_raw) <= 1.0 or abs(s.trend) < 1.0) and s.time_since_last_step >= 30.0:
            observed_hz_change = hz - s.hz_at_last_step
            # Wenn die Frequenz in die erwartete Richtung reagiert hat:
            if (s.last_step_delta < 0 and observed_hz_change > 0.8) or (
                s.last_step_delta > 0 and observed_hz_change < -0.8
            ):
                # Reaktionszeit aktualisieren
                s.learned_reaction_time = round(
                    0.8 * s.learned_reaction_time + 0.2 * s.time_since_last_step, 1
                )
                s.learned_reaction_time = _clamp(s.learned_reaction_time, 35.0, 240.0)

                # Verstärkung (Hz/K) aktualisieren
                gain = abs(observed_hz_change) / max(0.05, abs(s.last_step_delta))
                s.learned_sensitivity = round(
                    0.85 * s.learned_sensitivity + 0.15 * gain, 1
                )
                s.learned_sensitivity = _clamp(s.learned_sensitivity, 6.0, 45.0)

            s.last_step_delta = 0.0
            s.hz_at_last_step = None

    # ==================================================================
    # 5. THERMISCHER RAUM-ÜBERHITZUNGSSCHUTZ
    # ==================================================================
    if room_temp is not None and room_temp >= (setpoint + p.max_room_overheat):
        v_out = _clamp(setpoint + 0.3, low, high)
        s.output = v_out
        s.time_since_last_step = 0.0
        s.stable_cycles = 0
        s.hz_prev2 = hz_v1
        s.hz_prev1 = hz
        return Result(
            output=v_out,
            published=round1(v_out),
            offset=round(setpoint - v_out, 2),
            error_hz=round(effective_target - hz, 1),
            mode=MODE_OVERHEAT,
            outdoor_bin=outdoor_bin,
            freq_bin=freq_bin,
            learned_offset=learned_offset,
            effective_target_hz=effective_target,
            learned_min_hz=s.learned_min_hz,
        )

    # ==================================================================
    # 6. BASIS-AUSGANGSWERT INITIALISIEREN
    # ==================================================================
    if s.output is None:
        init_offset = learned_offset
        if target_below_min:
            init_offset = max(init_offset, s.learned_min_offset)
        v_alt = _clamp(round1(setpoint - init_offset), low, high)
        s.output = v_alt
        s.time_since_last_step = 0.0
    else:
        v_alt = _clamp(s.output, low, high)

    current_offset = round(setpoint - v_alt, 2)
    err = effective_target - hz

    # ==================================================================
    # 7. ERKENNUNG VON MINDESTMODULATIONS-STAGNATION
    # ==================================================================
    # Wenn die Frequenz trotz kleinem Offset / wärmerem Sensor nicht weiter sinkt,
    # haben wir die physikalische Mindestmodulation der Anlage im aktuellen Betriebspunkt erreicht.
    if err < -p.deadband_hz and current_offset <= 0.1 and abs(s.trend) < 0.5:
        s.low_hz_stagnation_count += 1
        if s.low_hz_stagnation_count >= 3:
            # 3 Takte keine Abnahme -> das ist die tatsächliche Mindestmodulation!
            s.learned_min_hz = max(s.learned_min_hz, round(hz, 1))
            s.learned_min_offset = max(0.1, current_offset)
            effective_target = s.learned_min_hz
            err = effective_target - hz
            s.low_hz_stagnation_count = 0
    else:
        s.low_hz_stagnation_count = 0

    # ==================================================================
    # 8. REGELSCHRITT-ENTSCHEIDUNG
    # ==================================================================
    # Fall A: Im Totband (Ziel erreicht)
    if abs(err) <= p.deadband_hz:
        mode = MODE_MIN_MOD if target_below_min else MODE_HOLD
        v_cmd = v_alt
        s.stable_cycles += 1

        # Wenn die Frequenz mindestens 2 Takte im Totband stabil ist:
        if s.stable_cycles >= 2:
            new_learned = (1.0 - p.learning_rate) * learned_offset + p.learning_rate * current_offset
            new_learned = round(_clamp(new_learned, -0.2, p.max_offset), 2)
            s.learned_table[outdoor_bin][freq_bin] = new_learned
            s.current_learned_offset = new_learned
            if target_below_min or abs(hz - s.learned_min_hz) <= p.deadband_hz:
                s.learned_min_offset = round(
                    0.8 * s.learned_min_offset + 0.2 * max(0.05, current_offset), 2
                )

    # Fall B: Frequenz zu hoch (err < -deadband)
    elif err < -p.deadband_hz:
        mode = MODE_LOWER
        s.stable_cycles = 0

        # Wenn die Frequenz bereits dynamisch nach unten fällt: STILLHALTEN!
        if s.trend < -1.0:
            v_cmd = v_alt
        elif s.time_since_last_step >= (s.learned_reaction_time * 0.75):
            # Schrittgröße anpassen: bei großer Abweichung dynamisch größer, sonst 0,1 K
            step_k = 0.1
            if abs(err) >= 10.0 and s.learned_sensitivity > 0:
                step_k = min(0.3, max(0.1, round1(abs(err) / s.learned_sensitivity * 0.5)))

            # Wenn wir uns der Mindestmodulation nähern, nie wärmer als der Haltepunkt stellen,
            # damit die Anlage keinesfalls ausschaltet!
            cand_cmd = round1(v_alt + step_k)
            max_allowed_temp = setpoint - max(0.0, s.learned_min_offset - 0.1)
            if target_below_min and cand_cmd > max_allowed_temp:
                v_cmd = round1(max_allowed_temp)
                mode = MODE_MIN_MOD
            else:
                v_cmd = cand_cmd

            if round1(v_cmd) != round1(v_alt):
                s.last_step_delta = round(v_cmd - v_alt, 2)
                s.hz_at_last_step = hz
                s.time_since_last_step = 0.0
        else:
            v_cmd = v_alt

    # Fall C: Frequenz zu niedrig (err > deadband)
    else:
        mode = MODE_RAISE
        s.stable_cycles = 0

        # Wenn der Kompressor bereits nach oben beschleunigt: STILLHALTEN!
        if s.trend > 1.0:
            v_cmd = v_alt
        elif s.time_since_last_step >= s.learned_reaction_time:
            step_k = 0.1
            if abs(err) >= 10.0 and s.learned_sensitivity > 0:
                step_k = min(0.3, max(0.1, round1(abs(err) / s.learned_sensitivity * 0.5)))

            v_cmd = round1(v_alt - step_k)
            if round1(v_cmd) != round1(v_alt):
                s.last_step_delta = round(v_cmd - v_alt, 2)
                s.hz_at_last_step = hz
                s.time_since_last_step = 0.0
        else:
            v_cmd = v_alt

    # ==================================================================
    # 9. ABSCHLUSS & SPEICHERUNG
    # ==================================================================
    # Schutz vor Ausgehen: Wenn Ziel unter Mindestmodulation liegt, darf der Sensor
    # niemals so warm werden, dass die Anlage abschaltet (mindestens minimaler Heizbedarf)
    if target_below_min and hz <= (s.learned_min_hz + p.deadband_hz):
        safe_max_temp = setpoint - max(0.0, s.learned_min_offset - 0.1)
        v_cmd = min(v_cmd, safe_max_temp)

    v_cmd = _clamp(v_cmd, low, high)
    s.output = v_cmd
    s.hz_prev2 = hz_v1
    s.hz_prev1 = hz

    return Result(
        output=v_cmd,
        published=round1(v_cmd),
        offset=round(setpoint - v_cmd, 2),
        error_hz=round(effective_target - hz, 1),
        mode=mode,
        outdoor_bin=outdoor_bin,
        freq_bin=freq_bin,
        learned_offset=s.current_learned_offset,
        effective_target_hz=effective_target,
        learned_min_hz=s.learned_min_hz,
    )
