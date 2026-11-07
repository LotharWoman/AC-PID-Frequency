"""Tests für den intelligenten, selbstlernenden Regelkern (ohne Home Assistant)."""

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
MODE_MIN_MOD = regelung.MODE_MIN_MOD
MODE_DEFROST = regelung.MODE_DEFROST
MODE_OVERHEAT = regelung.MODE_OVERHEAT


def test_initial_step_uses_learned_base_offset():
    """Beim Erststart wird der passende gelernte Erfahrungswert direkt angesetzt."""
    s = State()
    p = Params()
    # Ziel 30 Hz bei normaler Außentemperatur (8 °C) -> normal/mid_low (default 0.35 K)
    res = step(p, s, setpoint=21.0, hz=15.0, target_hz=30.0, outdoor_temp=8.0)
    assert res.outdoor_bin == OUTDOOR_BIN_NORMAL
    assert res.freq_bin == FREQ_BIN_MID_LOW
    assert res.learned_offset == 0.35
    assert res.published == 20.7  # 21.0 - 0.35 = 20.65 -> 20.7


def test_reaction_time_observation_window():
    """Respektiert die Totzeit der Anlage: macht nicht jede Minute ungeduldig einen Schritt."""
    s = State()
    s.learned_reaction_time = 120.0
    p = Params(interval_s=60.0)
    # Takt 1: Start bei 20.7
    res1 = step(p, s, 21.0, 15.0, 30.0, outdoor_temp=8.0)
    val1 = res1.published

    # Takt 2 (nach 60s): Frequenz stagniert bei 15 Hz, aber Reaktionszeit ist noch nicht um
    res2 = step(p, s, 21.0, 15.0, 30.0, outdoor_temp=8.0)
    assert res2.published == val1  # Keine vorzeitige Änderung!

    # Takt 3 (nach 120s): Reaktionszeit erreicht und Frequenz stagniert -> behutsamer Schritt
    res3 = step(p, s, 21.0, 15.0, 30.0, outdoor_temp=8.0)
    assert res3.published < val1


def test_patience_when_compressor_actively_accelerating():
    """Wenn der Kompressor bereits nach oben beschleunigt, stillhalten!"""
    s = State()
    s.learned_reaction_time = 120.0
    p = Params(interval_s=60.0)
    # Takt 1
    step(p, s, 21.0, 15.0, 30.0, outdoor_temp=8.0)
    # Takt 2 (nach 60s)
    step(p, s, 21.0, 15.0, 30.0, outdoor_temp=8.0)
    # Takt 3 (nach 120s): Kompressor beschleunigt kräftig (15 -> 20 Hz)
    res = step(p, s, 21.0, 20.0, 30.0, outdoor_temp=8.0)
    # Trotz abgelaufener Zeit darf er keinen neuen Schritt nachlegen!
    assert res.published == s.output


def test_deadband_learning_updates_table():
    """Im Totband lernt der Regler nach Stabilisierung den exakten Arbeitspunkt."""
    s = State()
    p = Params()
    # Einrichten mit Ziel 30 Hz bei 20.6 K (Offset 0.4 K)
    s.output = 20.6
    # Takt 1 im Totband (29 Hz)
    step(p, s, 21.0, 29.0, 30.0, outdoor_temp=8.0)
    assert s.stable_cycles == 1
    initial_learned = s.current_learned_offset

    # Takt 2 im Totband (30 Hz) -> Lernen greift!
    res = step(p, s, 21.0, 30.0, 30.0, outdoor_temp=8.0)
    assert res.mode == MODE_HOLD
    assert s.stable_cycles == 2
    # Der gelernte Offset nähert sich 0.4 K an
    assert s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] > initial_learned


def test_defrost_freezes_state_and_recovers_gracefully():
    """Während des Abtauens pausiert der Regler und stabilisiert sich danach 120s."""
    s = State()
    s.output = 20.7
    p = Params(interval_s=60.0)
    # Kompressor dreht auf 75 Hz (Abtau-Spitze), aber Defrost ist aktiv!
    res = step(p, s, 21.0, 75.0, 30.0, defrost=True)
    assert res.mode == MODE_DEFROST
    assert res.published == 20.7  # Unverändert gehalten!
    assert s.was_defrosting is True

    # Defrost beendet -> Post-Defrost Stabilisierung greift
    res_rec = step(p, s, 21.0, 25.0, 30.0, defrost=False)
    assert res_rec.mode == MODE_DEFROST
    assert s.post_defrost_remaining == 60.0
    assert res_rec.published == 20.7  # Keine unbedachte Reaktion auf den Hz-Sprung


def test_room_overheat_protection():
    """Wird der echte Raum zu warm, greift die thermische Drosselung."""
    s = State()
    p = Params(max_room_overheat=1.0)
    s.output = 20.6
    # Soll 21.0, Raumtemp 22.2 °C (mehr als Soll + 1.0 K)
    res = step(p, s, setpoint=21.0, hz=30.0, target_hz=30.0, room_temp=22.2)
    assert res.mode == MODE_OVERHEAT
    # Sensor wird über Soll gestellt, um die Anlage abzutouren
    assert res.published >= 21.0


def test_target_below_learned_min_modulation_maintains_stable_minimum():
    """Liegt die Ziel-Hz unter der Mindestmodulation, hält der Regler die Mindestmodulation stabil."""
    s = State()
    s.learned_min_hz = 28.0
    s.learned_min_offset = 0.20
    s.output = 20.8
    p = Params()

    # Nutzer fordert 18 Hz an, die Anlage kann aber nur 28 Hz
    res = step(p, s, setpoint=21.0, hz=28.0, target_hz=18.0)
    assert res.effective_target_hz == 28.0
    assert res.mode == MODE_MIN_MOD
    # Sensor wird nicht weiter wärmer gestellt als der sichere Haltepunkt
    assert res.published <= 21.0


def test_compressor_shutoff_detection_learns_min_hz_and_restarts():
    """Geht die Anlage beim Versuch abzusenken aus (0 Hz), lernt der Regler das Minimum und startet sie wieder."""
    s = State()
    s.last_running_hz = 27.0
    s.last_target_hz = 20.0
    s.current_learned_offset = 0.15
    p = Params()

    # Kompressor geht auf 0 Hz aus
    res = step(p, s, setpoint=21.0, hz=0.0, target_hz=20.0)
    # Mindestmodulation gelernt: 27.0 Hz!
    assert s.learned_min_hz >= 27.0
    assert res.mode == MODE_RAISE
    # Sendetemperatur kälter als Sollwert, damit die Anlage zuverlässig wieder anspringt
    assert res.published < 21.0


def test_learning_reaction_time_from_step_response():
    """Lernt die Reaktionszeit dynamisch aus der gemessenen Sprungantwort."""
    s = State()
    s.learned_reaction_time = 90.0
    s.time_since_last_step = 100.0
    s.output = 20.7
    p = Params(interval_s=30.0)

    # Takt 0: Regler macht Schritt kälter (20.7 -> 20.6)
    step(p, s, setpoint=21.0, hz=20.0, target_hz=35.0)
    assert s.last_step_delta < 0
    assert s.hz_at_last_step == 20.0

    # Takt 1: nach 30s steigt die Frequenz auf 25 Hz
    step(p, s, setpoint=21.0, hz=25.0, target_hz=35.0)

    # Takt 2: nach 60s verharrt die Frequenz bei 25 Hz (Plateau erreicht)
    step(p, s, setpoint=21.0, hz=25.0, target_hz=35.0)
    # Die gelernte Reaktionszeit passt sich in Richtung 60s an (90 -> 84)
    assert s.learned_reaction_time < 90.0


def test_outdoor_bins_separate_learning():
    """Änderungen in der Frostzone (cold) verändern nicht die Werte der Übergangszone (normal)."""
    s = State()
    p = Params()
    # In Cold-Zone (-2 °C) lernen
    s.output = 20.3  # Offset 0.7 K
    step(p, s, 21.0, 30.0, 30.0, outdoor_temp=-2.0)
    step(p, s, 21.0, 30.0, 30.0, outdoor_temp=-2.0)

    # Cold hat gelernt:
    assert s.learned_table[OUTDOOR_BIN_COLD][FREQ_BIN_MID_LOW] != regelung.DEFAULT_LEARNED_OFFSETS[OUTDOOR_BIN_COLD][FREQ_BIN_MID_LOW]
    # Normal und Warm sind unberührt:
    assert s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] == regelung.DEFAULT_LEARNED_OFFSETS[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW]
    assert s.learned_table[OUTDOOR_BIN_WARM][FREQ_BIN_MID_LOW] == regelung.DEFAULT_LEARNED_OFFSETS[OUTDOOR_BIN_WARM][FREQ_BIN_MID_LOW]


def test_reset_learning():
    """Reset setzt alle gelernten Tabellenwerte und Anlageneigenschaften zurück."""
    s = State()
    s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] = 0.99
    s.learned_min_hz = 32.0
    s.reset_learning()
    assert s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] == 0.35
    assert s.learned_min_hz == 15.0
