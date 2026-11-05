"""Regelkern des Hz-Deckels (Regler aus, Anlage regelt mit der echten Raumtemperatur selbst).

Reine Logik ohne Home-Assistant-Abhängigkeit, damit sie einzeln testbar ist.

Hintergrund (aus dem Verlauf eines sonnigen Tages): Die Anlage reagiert mit mehreren Minuten
Verzögerung und läuft auch bei unverändertem Sensorwert weiter hoch (sie integriert die
Abweichung zum Sollwert). Ein harter Notbremsen-Sprung und ein langsamer Rückweg erzeugen
deshalb einen Zyklus von ~35 Hz bis ~75 Hz. Der Deckel arbeitet darum anders als der
normale Regelkern:

* Bremsen in Stufen relativ zum aktuellen Wert statt Sprung auf Soll + Offset.
* Vorausschauen: Der Sensor wird schon angehoben, wenn die Hz auf die Grenze zulaufen.
* Beschleunigt die Anlage von selbst, wird der Sensor nicht weiter abgesenkt.
* Liegen die Hz weit unter dem Ziel, geht der Rückweg schneller (größerer Schritt).
* Steuerung nach Soll-Anstieg: Weit unter dem Ziel wird ein Anstieg von bis zu 3 Hz/min gewünscht,
  nahe am Ziel ~0. Der Sensor wird nur bewegt, wenn der echte Anstieg davon abweicht. Nach
  jedem Schritt wird die Totzeit der Anlage abgewartet.
* Der Regelwert liegt nie unter der echten Raumtemperatur (kein Aufwickeln).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .regelung import Params, round1

MODE_BRAKE = "brake"
MODE_RAISE = "raise"  # Sensor wird kälter gestellt, damit die Anlage mehr leistet
MODE_LOWER = "lower"  # Sensor wird wärmer gestellt, damit die Anlage weniger leistet
MODE_HOLD = "hold"

LOOKAHEAD_MIN = 3.0  # So weit (Minuten) wird die Hz-Entwicklung vorausgeschaut
FAST_BELOW_HZ = 15.0  # Weiter als das unter dem Ziel: ein Schritt je Takt statt je Reaktionszeit
TREND_WINDOW = 4  # Takte für die Trendbildung (3 Intervalle)
STEP_K = 0.1
BRAKE_STEP_BASE_K = 0.2
BRAKE_STEP_PER_HZ_K = 0.05
BRAKE_STEP_MAX_K = 0.5
FALLING_BLOCK_HZ_PER_MIN = -3.0  # Fällt sie über der Notbremse schon so schnell, wird nicht nachgelegt
APPROACH_MIN = 6.0  # In dieser Zeit (Minuten) soll die Frequenz das Ziel erreichen
MAX_APPROACH_HZ_PER_MIN = 3.0  # Schneller als das soll der Anstieg nie sein
FAST_GATE_FACTOR = 1.0  # Wartezeit zwischen Schritten = Reaktionszeit (Faktor)
FAST_STEP_K = 0.2  # weit unter dem Ziel: größerer Schritt für den schnelleren Rückweg
TREND_TOLERANCE = 0.75  # Hz/min Abweichung von der gewünschten Änderung ohne Eingriff
RELEASE_MARGIN_K = 0.3  # Freigabe erst, wenn die echte Temperatur so nah am Soll liegt


@dataclass
class CapState:
    """Gedächtnis des Deckels (wird nicht gespeichert)."""

    output: float | None = None
    time_since_last_step: float = 1e6  # erster Schritt sofort erlaubt
    hz_hist: deque = field(default_factory=lambda: deque(maxlen=TREND_WINDOW))


@dataclass(frozen=True)
class CapResult:
    output: float  # Regelwert (nie unter der echten Raumtemperatur)
    error_hz: float
    mode: str
    trend_hz_per_min: float


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _trend(s: CapState, interval_s: float) -> float:
    """Hz-Änderung je Minute über das Trendfenster."""
    if len(s.hz_hist) < 2:
        return 0.0
    minutes = (len(s.hz_hist) - 1) * interval_s / 60.0
    return (s.hz_hist[-1] - s.hz_hist[0]) / minutes


def can_release(setpoint: float, ref: float, output: float, hz: float, brake_hz: float) -> bool:
    """Deckel freigeben, wenn die Anlage mit der echten Temperatur von selbst darunter bleibt.

    Dazu muss der Raum nah am Sollwert liegen, der Regelwert bis auf die echte Temperatur
    zurückgenommen sein und die Frequenz unter der Notbremse liegen.
    """
    return (
        ref >= setpoint - RELEASE_MARGIN_K
        and output <= round1(ref)
        and hz <= brake_hz
    )


def step_cap(
    p: Params,
    s: CapState,
    setpoint: float,
    hz: float,
    brake_hz: float,
    cap_target: float,
    ref: float,
) -> CapResult:
    """Ein Takt des Deckels. ``ref`` ist die echte Raumtemperatur (Untergrenze des Ausgangs)."""
    s.time_since_last_step += p.interval_s
    s.hz_hist.append(hz)
    trend = _trend(s, p.interval_s)
    err = cap_target - hz

    low = ref
    high = max(setpoint + p.max_offset, ref)
    if s.output is None:
        s.output = ref
    out = _clamp(s.output, low, high)

    pred_up = hz + max(trend, 0.0) * LOOKAHEAD_MIN  # Hz in ein paar Minuten, wenn es so weitergeht
    mode = MODE_HOLD

    before = out
    if hz > brake_hz:
        # Notbremse in Stufen: je weiter drüber, desto größer der Schritt. Nach einem Schritt
        # wird die Wirkung abgewartet (Totzeit der Anlage), es sei denn, sie steigt weiter.
        mode = MODE_BRAKE
        gate = p.interval_s if trend >= 2.0 else p.reaction_time_s
        if trend > FALLING_BLOCK_HZ_PER_MIN and s.time_since_last_step >= gate:
            excess = hz - brake_hz
            step_k = min(BRAKE_STEP_MAX_K, BRAKE_STEP_BASE_K + BRAKE_STEP_PER_HZ_K * excess)
            out = round1(out + step_k)
    else:
        # Gewünschte Hz-Änderung je Minute: weit unter dem Ziel zügig hoch, nahe am Ziel
        # (und über dem Ziel) ruhig bzw. abwärts. So pendelt sich die Anlage dort ein, wo
        # sie ohne weiteres Zutun stehen bleibt (Änderung ~0), statt zu überschwingen.
        trend_des = _clamp(err / APPROACH_MIN, -MAX_APPROACH_HZ_PER_MIN, MAX_APPROACH_HZ_PER_MIN)
        dev = trend - trend_des
        if dev > TREND_TOLERANCE:
            # Zu schnell hoch (oder zu langsam runter): wärmer stellen
            mode = MODE_LOWER
            gate = p.interval_s if pred_up > brake_hz else p.reaction_time_s
            if s.time_since_last_step >= gate:
                out = round1(out + STEP_K)
        elif dev < -TREND_TOLERANCE:
            # Zu langsam hoch (oder zu schnell runter): kälter stellen
            mode = MODE_RAISE
            far = err > FAST_BELOW_HZ
            gate = p.reaction_time_s * FAST_GATE_FACTOR if far else p.reaction_time_s
            if s.time_since_last_step >= gate:
                out = round1(out - (FAST_STEP_K if far else STEP_K))

    out = _clamp(out, low, high)
    if round1(out) != round1(_clamp(before, low, high)):
        s.time_since_last_step = 0.0  # nur ein echter Schritt startet die Wartezeit
    s.output = out
    return CapResult(
        output=round1(out),
        error_hz=round(err, 1),
        mode=mode,
        trend_hz_per_min=round(trend, 1),
    )
