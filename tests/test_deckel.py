"""Tests des Regelkerns mit einem dynamischen Anlagenmodell (Mindestmodulation, Trägheit, Defrost)."""

from __future__ import annotations

from collections import deque
import importlib.util
from pathlib import Path
import sys

_PATH = Path(__file__).parent.parent / "custom_components" / "ac_pid_frequency" / "regelung.py"
_spec = importlib.util.spec_from_file_location("regelung", _PATH)
regelung = importlib.util.module_from_spec(_spec)
sys.modules["regelung"] = regelung
_spec.loader.exec_module(regelung)

Params = regelung.Params
State = regelung.State
step = regelung.step

P = Params(interval_s=60.0)
SOLL = 21.0


class RealisticAcModel:
    """Modell einer echten Inverter-Klimaanlage.

    Besonderheiten:
    * Verzögerung (Totzeit / Kommunikationsintervall)
    * Träger Anstieg / Abfall (Ramp-Rate)
    * Feste physikalische Mindestmodulation (min_hz, z. B. 26.0 Hz):
      Kann nicht darunter laufen. Wird der Sensor wärmer als Soll + 0.3 K, schaltet
      die Anlage komplett aus (0 Hz, Thermo-Off).
    * Defrost-Zyklen
    """

    def __init__(self, start_hz: float = 40.0, min_hz: float = 26.0, delay_ticks: int = 2) -> None:
        self.hz = start_hz
        self.min_hz = min_hz
        self.is_off = False
        self.buf: deque[float] = deque([0.35] * delay_ticks, maxlen=delay_ticks)

    def tick(self, sensor: float, defrost: bool = False) -> float:
        if defrost:
            self.hz = 72.0  # Hohe Abtaufrequenz
            return self.hz

        # Offset zur Solltemperatur
        d = SOLL - sensor
        self.buf.append(d)
        delayed_d = self.buf[0]

        if delayed_d < -0.25:
            # Zu warm -> Kompressor schaltet ab (Thermo-Off)
            self.is_off = True
            self.hz = 0.0
            return self.hz

        if self.is_off:
            if delayed_d >= 0.2:
                # Genug Kältebedarf -> Kompressor schaltet wieder ein
                self.is_off = False
                self.hz = self.min_hz + 5.0
            else:
                self.hz = 0.0
            return self.hz

        # Normale Modulation: Strebt Frequenz proportional zum Offset an
        desired_hz = max(self.min_hz, 20.0 + delayed_d * 30.0)
        # Träge Rampenbewegung
        if self.hz < desired_hz:
            self.hz = min(desired_hz, self.hz + 3.0)
        elif self.hz > desired_hz:
            self.hz = max(desired_hz, self.hz - 3.0)

        # Kann nicht unter min_hz modulieren
        self.hz = max(self.min_hz, min(90.0, self.hz))
        return self.hz


def test_simulation_target_below_minimum_modulation_prevents_cycling():
    """Wenn die Soll-Hz unter der Mindestmodulation liegt, lernt der Algorithmus

    die Grenze und stabilisiert die Anlage auf dem Minimum, sodass sie dauerhaft
    durchläuft und nicht mehr ausgeht.
    """
    ac = RealisticAcModel(start_hz=35.0, min_hz=26.0, delay_ticks=2)
    s = State()
    target_hz = 18.0  # Unerreichbar niedrig!

    hz = ac.hz
    trace = []
    zero_count_after_settling = 0

    # 180 Minuten Laufzeit simulieren
    for minute in range(180):
        res = step(P, s, setpoint=SOLL, hz=hz, target_hz=target_hz)
        hz = ac.tick(res.published)
        trace.append(hz)
        if minute > 45 and hz == 0:
            zero_count_after_settling += 1

    # Nach dem anfänglichen Einschwingen und Lernen des Limits:
    assert s.learned_min_hz >= 25.0
    settled = trace[60:]
    # Die Anlage schaltet nach dem Lernen nie mehr aus!
    assert zero_count_after_settling == 0
    # Die Frequenz bleibt stabil auf oder unmittelbar bei der Mindestmodulation (26 Hz)
    assert 25.0 <= min(settled) <= 27.0
    assert max(settled) <= 30.0


def test_simulation_through_defrost_cycle():
    """Simulation eines Betriebs mit Abtauung (Defrost).

    Nach dem Abtauen fängt der Regler die Anlage ruhig ab, ohne Überschwinger.
    """
    ac = RealisticAcModel(start_hz=40.0, min_hz=25.0)
    s = State()
    target_hz = 35.0

    hz = ac.hz
    for minute in range(120):
        # Minute 30 bis 35: Defrost aktiv
        is_defrost = 30 <= minute <= 35
        res = step(P, s, setpoint=SOLL, hz=hz, target_hz=target_hz, defrost=is_defrost)
        hz = ac.tick(res.published, defrost=is_defrost)

    # Nach Minute 60 soll die Anlage wieder sauber auf Ziel 35 Hz eingependelt sein
    assert abs(hz - 35.0) <= 2.5
