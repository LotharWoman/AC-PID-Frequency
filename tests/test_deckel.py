"""Tests des Hz-Deckel-Regelkerns, inkl. grobem Anlagenmodell (träge, integrierend)."""

from __future__ import annotations

from collections import deque

from custom_components.ac_pid_frequency.deckel import (
    CapState,
    can_release,
    step_cap,
)
from custom_components.ac_pid_frequency.regelung import Params

P = Params()  # Takt 60 s, Reaktionszeit 120 s, Totband 3 Hz, max_offset 1,0 K
SOLL, BRAKE, TARGET = 21.0, 70.0, 65.0


def _step(s: CapState, hz: float, ref: float = 20.3):
    return step_cap(P, s, SOLL, hz, BRAKE, TARGET, ref)


def test_brake_is_staged_relative_to_real_temperature_not_a_jump() -> None:
    s = CapState()
    r = _step(s, 74.0)
    assert r.mode == "brake"
    # Start bei der echten Temperatur (20,3), dann nur ein Schritt, kein Sprung auf Soll + 0,5
    assert 20.3 < r.output <= 20.3 + 0.5
    r2 = _step(s, 77.0)  # steigt weiter schnell: sofort nachlegen
    assert r2.output > r.output
    assert r2.output < SOLL + 0.5


def test_brake_waits_for_effect_before_next_step() -> None:
    s = CapState()
    first = _step(s, 74.0).output
    second = _step(s, 74.0).output  # nur 60 s später, Hz stehen: Wirkung abwarten (Totzeit)
    assert second == first
    third = _step(s, 74.0).output  # Reaktionszeit (120 s) verstrichen, noch drüber: nachlegen
    assert third > first


def test_bigger_excess_gives_bigger_brake_step() -> None:
    small = _step(CapState(), 71.0).output
    big = _step(CapState(), 80.0).output
    assert big > small


def test_no_lowering_while_plant_is_accelerating_by_itself() -> None:
    s = CapState()
    s.output = 20.8
    out = []
    for hz in (44.0, 50.0, 56.0, 61.0):  # +5 Hz je Minute, noch unter dem Ziel
        out.append(_step(s, hz).output)
    assert max(out) <= 20.8  # nie kälter gestellt (Anlage läuft ohnehin hoch)
    assert min(out) >= 20.8 - 1e-9 or out[-1] >= out[0]


def test_early_warming_when_approaching_limit() -> None:
    s = CapState()
    s.output = 20.5
    _step(s, 54.0)
    _step(s, 58.0)
    before = _step(s, 60.0).output
    r = _step(s, 64.0)  # ~ +3 Hz/min: in 3 min deutlich über Ziel -> nicht weiter absenken
    assert r.mode == "lower"
    assert r.output >= before


def test_far_below_target_steps_down_then_waits_for_effect() -> None:
    s = CapState()
    s.output = 21.2
    a = _step(s, 40.0).output  # weit unter Ziel: größerer Schritt
    assert a < 21.2
    b = _step(s, 40.0).output  # 60 s später: Totzeit abwarten
    assert b == a
    c = _step(s, 40.0).output  # Reaktionszeit verstrichen
    assert c < b


def test_output_never_below_real_room_temperature() -> None:
    s = CapState()
    for _ in range(30):
        r = _step(s, 30.0, ref=20.6)
    assert r.output >= 20.6


def test_output_bounded_by_max_offset() -> None:
    s = CapState()
    for _ in range(30):
        r = _step(s, 90.0)
    assert r.output <= SOLL + P.max_offset


def test_release_needs_room_close_to_setpoint() -> None:
    # Echte Temperatur noch 0,7 K unter Soll: kein Freigeben, auch wenn Regelwert = echte Temperatur
    assert not can_release(SOLL, 20.3, 20.3, 50.0, BRAKE)
    # Raum nah am Soll und Regelwert zurückgenommen: frei
    assert can_release(SOLL, 20.8, 20.8, 50.0, BRAKE)
    # Regelwert noch über echter Temperatur: noch nicht
    assert not can_release(SOLL, 20.8, 21.0, 50.0, BRAKE)
    # Über der Notbremse nie
    assert not can_release(SOLL, 20.8, 20.8, 71.0, BRAKE)


# ---------------------------------------------------------------------- Anlagenmodell
class FakeAc:
    """Grobes Modell nach dem Verlauf vom 05.11.: Totzeit, träge, mit integrierendem Anteil.

    d = Soll - Sensor. Bei d = 0,45 K bleibt die Anlage ruhig bei ~45 Hz, bei größerem d
    läuft sie hoch, bei kleinerem fällt sie bis ~36 Hz.
    """

    def __init__(self, hz: float = 50.0, delay_min: int = 2) -> None:
        self.hz = hz
        self.buf: deque[float] = deque([0.45] * delay_min, maxlen=delay_min)

    def minute(self, sensor: float) -> float:
        self.buf.append(SOLL - sensor)
        d = self.buf[0]
        rate = max(-7.0, min(6.0, (d - 0.45) * 20.0))  # Hz je Minute
        self.hz = max(36.0, min(95.0, self.hz + rate))
        return self.hz


def _simulate(minutes: int, ref: float = 20.3, start_hz: float = 50.0):
    ac, s = FakeAc(start_hz), CapState()
    sensor, hz = ref, start_hz
    trace = []
    for _ in range(minutes):
        r = step_cap(P, s, SOLL, hz, BRAKE, TARGET, ref)
        sensor = max(r.output, ref)
        hz = ac.minute(sensor)
        trace.append(hz)
    return trace


def test_simulation_cap_stays_near_limit_without_big_swings() -> None:
    for start in (74.0, 50.0, 40.0):
        trace = _simulate(240, start_hz=start)
        settled = trace[60:]  # nach der Einschwingphase
        assert max(trace) < 80
        assert max(settled) < 72
        assert min(settled) > 50  # kein Absacken auf 35 Hz wie zuvor
        assert sum(settled) / len(settled) > 58  # im Mittel nah an der Grenze (vorher ~46)


def test_simulation_with_longer_dead_time_never_runs_away() -> None:
    ac, s = FakeAc(74.0, delay_min=4), CapState()
    hz = 74.0
    peaks = []
    for _ in range(240):
        r = step_cap(P, s, SOLL, hz, BRAKE, TARGET, 20.3)
        hz = ac.minute(max(r.output, 20.3))
        peaks.append(hz)
    assert max(peaks) < 82
