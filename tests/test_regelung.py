"""Tests für den reinen Regelkern (ohne Home Assistant)."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

_PATH = Path(__file__).parent.parent / "custom_components" / "ac_pid_frequency" / "regelung.py"
_spec = importlib.util.spec_from_file_location("regelung", _PATH)
regelung = importlib.util.module_from_spec(_spec)
import sys

sys.modules["regelung"] = regelung  # dataclasses braucht das Modul in sys.modules
_spec.loader.exec_module(regelung)

Params, State, step = regelung.Params, regelung.State, regelung.step


# --------------------------------------------------------------------------------------
# Referenz: direkte Abschrift der YAML-Logik (klima_srk35_auto.yaml v8.1), unabhängig
# vom Produktivcode geschrieben. v_alt ist hier der letzte Ausgabewert.
# --------------------------------------------------------------------------------------
def yaml_reference(soll, hz, hz_v1, hz_v2, factor, v_alt, ziel_hz, notbremse):
    ziel = min(notbremse, ziel_hz)
    err = ziel - hz
    trend_1m = hz - hz_v1
    d_alt = soll - v_alt
    is_hunting = (trend_1m * (hz_v1 - hz_v2)) < 0 and abs(trend_1m) > 2.0
    if is_hunting:
        new_factor = max(0.6, factor - 0.1)
    elif abs(err) <= 3.0:
        new_factor = min(1.2, factor + 0.05)
    else:
        new_factor = max(0.8, factor)
    if hz > notbremse:
        d_raw = -0.5
    elif err > 3.0:
        d_raw = 0.6
    elif err < -3.0:
        d_raw = -0.4
    elif abs(err) <= 3.0:
        d_raw = min(0.3, max(-0.3, d_alt))
    else:
        d_raw = 0.0
    d_calc = round(d_raw * factor, 2)
    v_target = max(16.0, min(24.0, regelung.round1(soll - d_calc)))
    v_delta_max = 0.1 if err > 3.0 else 0.08
    diff = v_target - v_alt
    if err < -3.0:
        v_cmd = v_target
    elif diff > v_delta_max:
        v_cmd = round(v_alt + v_delta_max, 2)
    elif diff < -v_delta_max:
        v_cmd = round(v_alt - v_delta_max, 2)
    else:
        v_cmd = v_target
    return v_cmd, round(new_factor, 2)


def test_matches_yaml_reference_on_random_sequences():
    """Über viele Zufallsfolgen exakt das gleiche Ergebnis wie die YAML-Logik."""
    rnd = random.Random(1234)
    # Sicherheitsgrenze so weit aufmachen, dass sie die YAML-Referenz nicht beeinflusst
    params = Params(max_offset=100.0)
    for _ in range(200):
        soll = rnd.choice([19.0, 20.0, 20.5, 21.0, 22.0])
        target = rnd.choice([22, 30, 35, 48])
        brake = rnd.choice([60, 70, 80])
        s = State()
        hz_v1 = hz_v2 = None
        v_alt = soll
        factor = 1.0
        hz = rnd.uniform(0, 60)
        for _ in range(80):
            hz = max(0.0, hz + rnd.uniform(-9, 9))
            ref_v1 = hz_v1 if hz_v1 is not None else hz
            ref_v2 = hz_v2 if hz_v2 is not None else ref_v1
            exp_v, exp_f = yaml_reference(soll, hz, ref_v1, ref_v2, factor, v_alt, target, brake)
            res = step(params, s, soll, hz, target, brake)
            assert abs(res.output - exp_v) < 1e-9, (soll, hz, target, brake)
            assert abs(res.factor - exp_f) < 1e-9
            v_alt, factor = exp_v, exp_f
            hz_v2, hz_v1 = ref_v1, hz


def test_hz_too_low_pushes_sensor_down_slowly():
    """Heizen: zu wenig Hz -> Sensor sinkt unter Soll, max. 0,1 K je Minute."""
    s = State()
    p = Params()
    values = [step(p, s, 21.0, 10.0, 40, 70).output for _ in range(10)]
    assert values[0] == 20.9
    assert all(a - b <= 0.1 + 1e-9 for a, b in zip(values, values[1:]))
    # läuft bis Soll - 0.6*Faktor (Faktor bleibt außerhalb des Totbands bei 1.0)
    assert min(values) >= 20.4 - 1e-9
    assert values[-1] < values[0]


def test_hz_too_high_drops_immediately():
    """Zu viel Hz -> Sensor springt sofort auf Soll + 0,4."""
    s = State(output=20.4)
    res = step(Params(), s, 21.0, 50.0, 30, 70)
    assert res.mode == "lower"
    assert res.output == 21.4


def test_deadband_holds_last_offset_limited():
    s = State(output=20.8)  # Offset 0.2 liegt im Haltebereich
    res = step(Params(), s, 21.0, 30.0, 30, 70)
    assert res.mode == "hold"
    assert res.output == 20.8
    # Großer alter Offset wird auf ±hold_limit begrenzt und langsam abgebaut
    s = State(output=20.4)
    res = step(Params(), s, 21.0, 30.0, 30, 70)
    assert res.mode == "hold"
    assert res.output == 20.48  # 0.08 K Schritt Richtung Soll-0.3


def test_emergency_brake_is_configurable_and_forces_negative_offset():
    s = State(output=21.0)
    res = step(Params(), s, 21.0, 72.0, 80, 70)  # Ziel 80 wird von Notbremse 70 gedeckelt
    assert res.mode == "brake"
    assert res.offset < 0
    # mit höherer Notbremse greift sie nicht
    s = State(output=21.0)
    res = step(Params(), s, 21.0, 72.0, 80, 85)
    assert res.mode != "brake"


def test_learning_factor_drops_when_hunting_and_rises_in_deadband():
    p = Params()
    s = State(factor=1.0)
    step(p, s, 21.0, 30.0, 30, 70)  # Historie füllen
    step(p, s, 21.0, 40.0, 30, 70)  # +10
    res = step(p, s, 21.0, 30.0, 30, 70)  # -10 -> Pendeln
    assert res.hunting
    assert res.factor == 0.95  # 1.0 -> 1.05 (Totband) -> 1.05 (außerhalb) -> 0.95 (Pendeln)
    s = State(factor=1.0)
    res = step(p, s, 21.0, 30.0, 30, 70)
    assert res.factor == 1.05
    for _ in range(10):
        res = step(p, s, 21.0, 30.0, 30, 70)
    assert res.factor == 1.2  # Obergrenze


def test_safety_clamp_relative_to_setpoint():
    p = Params(max_offset=0.5)
    s = State(output=30.0)  # unsinniger Altwert
    res = step(p, s, 21.0, 30.0, 30, 70)
    assert 20.5 <= res.output <= 21.5


def test_interval_scales_rate_limit():
    s30, s60 = State(), State()
    a = step(Params(interval_s=30), s30, 21.0, 10.0, 40, 70).output
    b = step(Params(interval_s=60), s60, 21.0, 10.0, 40, 70).output
    assert round(21.0 - a, 2) == 0.05
    assert round(21.0 - b, 2) == 0.1


def test_published_value_has_one_decimal():
    s = State()
    p = Params()
    for _ in range(30):
        res = step(p, s, 21.0, 10.0, 40, 70)
        assert res.published == round(res.published, 1)
