"""Tests für den intelligenten Regel- und Lernkern (ohne Home Assistant)."""

from __future__ import annotations

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
OUTDOOR_BIN_COLD = regelung.OUTDOOR_BIN_COLD
OUTDOOR_BIN_NORMAL = regelung.OUTDOOR_BIN_NORMAL
OUTDOOR_BIN_WARM = regelung.OUTDOOR_BIN_WARM
FREQ_BIN_MID_LOW = regelung.FREQ_BIN_MID_LOW
MODE_HOLD = regelung.MODE_HOLD
MODE_RAISE = regelung.MODE_RAISE
MODE_LOWER = regelung.MODE_LOWER
MODE_BRAKE = regelung.MODE_BRAKE
MODE_DEFROST = regelung.MODE_DEFROST
MODE_OVERHEAT = regelung.MODE_OVERHEAT


def test_initial_step_uses_learned_base_offset():
    """Beim Erststart wird der passende gelernte Erfahrungswert direkt angesetzt."""
    s = State()
    p = Params()
    # Ziel 30 Hz bei normaler Außentemperatur (8 °C) -> normal/mid_low (default 0.35 K)
    res = step(p, s, setpoint=21.0, hz=15.0, target_hz=30.0, brake_hz=70.0, outdoor_temp=8.0)
    assert res.outdoor_bin == OUTDOOR_BIN_NORMAL
    assert res.freq_bin == FREQ_BIN_MID_LOW
    assert res.learned_offset == 0.35
    assert res.published == 20.7  # 21.0 - 0.35 = 20.65 -> 20.7


def test_reaction_time_observation_window():
    """Respektiert die Totzeit der Anlage: macht nicht jede Minute ungeduldig einen Schritt."""
    s = State()
    p = Params(interval_s=60.0, reaction_time_s=120.0)
    # Takt 1: Start bei 20.7
    res1 = step(p, s, 21.0, 15.0, 30.0, 70.0, outdoor_temp=8.0)
    val1 = res1.published

    # Takt 2 (nach 60s): Frequenz stagniert bei 15 Hz, aber 120s sind noch nicht um
    res2 = step(p, s, 21.0, 15.0, 30.0, 70.0, outdoor_temp=8.0)
    assert res2.published == val1  # Keine vorzeitige Änderung!

    # Takt 3 (nach 120s): 120s sind erreicht und Frequenz stagniert -> behutsamer 0,1-K-Schritt
    res3 = step(p, s, 21.0, 15.0, 30.0, 70.0, outdoor_temp=8.0)
    assert round(val1 - res3.published, 1) == 0.1


def test_patience_when_compressor_actively_accelerating():
    """Wenn der Kompressor bereits nach oben beschleunigt (Trend >= 1.5 Hz), stillhalten!"""
    s = State()
    p = Params(interval_s=60.0, reaction_time_s=120.0)
    # Takt 1
    step(p, s, 21.0, 15.0, 30.0, 70.0, outdoor_temp=8.0)
    # Takt 2 (nach 60s)
    step(p, s, 21.0, 15.0, 30.0, 70.0, outdoor_temp=8.0)
    # Takt 3 (nach 120s): Kompressor beschleunigt kräftig (15 -> 20 Hz, Trend +5)
    res = step(p, s, 21.0, 20.0, 30.0, 70.0, outdoor_temp=8.0)
    # Trotz abgelaufener 120s darf er keinen neuen Schritt nachlegen!
    assert res.published == s.output


def test_deadband_learning_updates_table():
    """Im Totband lernt der Regler nach Stabilisierung den exakten Arbeitspunkt."""
    s = State()
    p = Params()
    # Einrichten mit Ziel 30 Hz bei 20.6 K (Offset 0.4 K)
    s.output = 20.6
    # Takt 1 im Totband (29 Hz)
    step(p, s, 21.0, 29.0, 30.0, 70.0, outdoor_temp=8.0)
    assert s.stable_cycles == 1
    initial_learned = s.current_learned_offset

    # Takt 2 im Totband (30 Hz) -> Lernen greift!
    res = step(p, s, 21.0, 30.0, 30.0, 70.0, outdoor_temp=8.0)
    assert res.mode == MODE_HOLD
    assert s.stable_cycles == 2
    # Der gelernte Offset nähert sich 0.4 K an
    assert s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] > initial_learned


def test_overshoot_penalizes_learned_offset():
    """Bei Überschwingern über das Ziel wird der gelernte Wert automatisch gedämpft."""
    s = State()
    p = Params(deadband_hz=3.0, overshoot_penalty=0.05)
    s.output = 20.5
    learned_before = s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW]

    # Frequenz schießt auf 36 Hz (Ziel 30, Totband 3, Überschwinger > 35 Hz)
    res = step(p, s, 21.0, 36.0, 30.0, 70.0, outdoor_temp=8.0)
    assert res.mode == MODE_LOWER
    assert s.overshoot_detected is True
    assert s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] == round(learned_before - 0.05, 2)


def test_defrost_freezes_state_and_avoids_brake():
    """Während des Abtauens pausiert der Regler und löst keine Notbremse aus."""
    s = State()
    s.output = 20.7
    p = Params()
    # Kompressor dreht auf 75 Hz (über Notbremse 70 Hz), aber Defrost ist aktiv!
    res = step(p, s, 21.0, 75.0, 30.0, 70.0, defrost=True)
    assert res.mode == MODE_DEFROST
    assert res.published == 20.7  # Unverändert gehalten!
    assert s.overshoot_detected is False


def test_room_overheat_protection():
    """Wird der echte Raum zu warm, greift die thermische Notbremse."""
    s = State()
    p = Params(max_room_overheat=1.0)
    s.output = 20.6
    # Soll 21.0, Raumtemp 22.2 °C (mehr als Soll + 1.0 K)
    res = step(p, s, setpoint=21.0, hz=30.0, target_hz=30.0, brake_hz=70.0, room_temp=22.2)
    assert res.mode == MODE_OVERHEAT
    # Sensor wird auf 21.4 (Soll + 0.4) gestellt, um die Anlage abzutouren
    assert res.published >= 21.0


def test_emergency_brake_on_high_hz():
    """Notbremse zieht sofort bei Überschreiten von brake_hz (wenn kein Defrost)."""
    s = State()
    s.output = 20.6
    p = Params(offset_brake=0.5)
    res = step(p, s, 21.0, 75.0, 30.0, 70.0)
    assert res.mode == MODE_BRAKE
    assert res.published == 21.5  # 21.0 + 0.5


def test_outdoor_bins_separate_learning():
    """Änderungen in der Frostzone (cold) verändern nicht die Werte der Übergangszone (normal)."""
    s = State()
    p = Params()
    # In Cold-Zone (-2 °C) lernen
    s.output = 20.3  # Offset 0.7 K
    step(p, s, 21.0, 30.0, 30.0, 70.0, outdoor_temp=-2.0)
    step(p, s, 21.0, 30.0, 30.0, 70.0, outdoor_temp=-2.0)

    # Cold hat gelernt:
    assert s.learned_table[OUTDOOR_BIN_COLD][FREQ_BIN_MID_LOW] != regelung.DEFAULT_LEARNED_OFFSETS[OUTDOOR_BIN_COLD][FREQ_BIN_MID_LOW]
    # Normal und Warm sind unberührt:
    assert s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] == regelung.DEFAULT_LEARNED_OFFSETS[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW]
    assert s.learned_table[OUTDOOR_BIN_WARM][FREQ_BIN_MID_LOW] == regelung.DEFAULT_LEARNED_OFFSETS[OUTDOOR_BIN_WARM][FREQ_BIN_MID_LOW]


def test_reset_learning():
    """Reset setzt alle gelernten Tabellenwerte auf Standard zurück."""
    s = State()
    s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] = 0.99
    s.reset_learning()
    assert s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] == 0.35
