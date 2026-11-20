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
MODE_POST_DEFROST = regelung.MODE_POST_DEFROST
MODE_RESTART_WAIT = regelung.MODE_RESTART_WAIT
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
    """Während des Abtauens pausiert der Regler und stabilisiert sich danach 240s."""
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
    assert res_rec.mode == MODE_POST_DEFROST
    assert s.post_defrost_remaining == 180.0  # 240 s Haltephase, ein Takt (60 s) verbraucht
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
    s.output = 20.9  # Sensor war warm (Soll - 0,1): der Regler wollte tiefer
    p = Params()

    # Kompressor geht auf 0 Hz aus
    res = step(p, s, setpoint=21.0, hz=0.0, target_hz=20.0)
    # Mindestmodulation gelernt: 27.0 Hz!
    assert s.learned_min_hz >= 27.0
    assert res.mode == MODE_RAISE
    # Sendetemperatur kälter als Sollwert, damit die Anlage zuverlässig wieder anspringt
    assert res.published < 21.0


def test_compressor_stop_from_high_hz_is_not_learned_as_min_hz():
    """Ein Stopp aus großer Höhe (z. B. 65 Hz bei Ziel 35 Hz) ist keine Mindestmodulation."""
    s = State()
    s.last_running_hz = 65.0
    s.output = 20.9
    before = dict(s.learned_min_table)
    step(Params(), s, setpoint=21.0, hz=0.0, target_hz=35.0)
    assert s.learned_min_table == before


def test_compressor_stop_with_cold_sensor_is_not_learned_as_min_hz():
    """War der Sensor kalt (wir wollten mehr Hz), ist der Stopp kein Mindestmodulations-Hinweis."""
    s = State()
    s.last_running_hz = 27.0
    s.output = 20.4  # 0,6 K unter Soll
    before = dict(s.learned_min_table)
    step(Params(), s, setpoint=21.0, hz=0.0, target_hz=20.0)
    assert s.learned_min_table == before


def test_learned_min_hz_is_capped_at_60():
    s = State()
    s.last_running_hz = 75.0
    s.output = 20.95
    before = dict(s.learned_min_table)
    step(Params(), s, setpoint=21.0, hz=0.0, target_hz=70.0)
    assert s.learned_min_table == before  # über 60 Hz nie als Minimum gelernt


def test_configured_zone_min_hz_allows_targets_below_old_default():
    """SRF50-Fall: Mindest-Hz 12 Hz im Übergangsbereich, Ziel 14 Hz wird nicht auf 18 Hz gehoben."""
    p = Params(min_hz_normal=12.0)
    s = State()
    s.learned_min_table = p.min_hz_map()
    res = step(p, s, setpoint=21.0, hz=14.0, target_hz=14.0, outdoor_temp=6.0)
    assert res.outdoor_bin == "normal"
    assert res.learned_min_hz == 12.0
    assert res.effective_target_hz == 14.0
    assert res.mode != MODE_MIN_MOD


def test_probing_and_reset_respect_configured_zone_floor():
    p = Params(min_hz_normal=12.0, probe_interval_min=1.0, interval_s=60.0)
    s = State()
    s.learned_min_table = {**p.min_hz_map(), "normal": 14.0}
    # User-Trigger (neues Ziel unter dem gelernten Minimum 14) setzt auf die eingestellte
    # Untergrenze (12), nicht auf 18
    step(p, s, setpoint=21.0, hz=14.0, target_hz=20.0, outdoor_temp=6.0)
    step(p, s, setpoint=21.0, hz=14.0, target_hz=13.0, outdoor_temp=6.0)
    assert s.learned_min_table["normal"] == 12.0


def test_no_restart_push_and_no_learning_while_room_is_warm():
    p = Params()
    s = State()
    s.last_running_hz = 20.0
    s.output = 21.3
    before = dict(s.learned_min_table)
    res = step(p, s, setpoint=21.0, hz=0.0, target_hz=20.0, real_room_temp=23.0)
    assert res.mode == MODE_RESTART_WAIT
    assert res.published == 21.3  # Soll + 0,3 K statt kaltem Anschub
    assert s.learned_min_table == before  # Stopp kam von der Raumtemperatur
    assert s.last_running_hz is None


def test_restart_push_when_room_below_setpoint_plus_margin():
    p = Params(restart_margin_k=0.5)
    s = State()
    res = step(p, s, setpoint=21.0, hz=0.0, target_hz=20.0, real_room_temp=21.4)
    assert res.mode == MODE_RAISE and res.published < 21.0
    res2 = step(p, State(), setpoint=21.0, hz=0.0, target_hz=20.0, real_room_temp=21.5)
    assert res2.mode == MODE_RESTART_WAIT


def test_restart_push_unchanged_without_real_room_sensor():
    res = step(Params(), State(), setpoint=21.0, hz=0.0, target_hz=20.0)
    assert res.mode == MODE_RAISE and res.published < 21.0


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
    assert s.learned_min_hz == 18.0


def test_reset_min_hz_only_resets_min_tables():
    """reset_min_hz setzt nur die Mindestmodulation zurück, behält aber gelernte Offsets."""
    s = State()
    s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] = 0.85
    s.learned_min_hz = 32.0
    s.reset_min_hz()
    assert s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] == 0.85
    assert s.learned_min_hz == 18.0


def test_user_trigger_resets_learned_min_hz_on_target_hz_change():
    """Säule 2: Ändert der Nutzer Ziel-Hz, wird das gelernte Minimum für erneuten Test freigegeben."""
    s = State()
    s.learned_min_table[OUTDOOR_BIN_NORMAL] = 26.0
    s.last_target_hz = 30.0
    p = Params()
    # Nutzer ändert Ziel-Hz von 30 auf 22
    step(p, s, setpoint=21.0, hz=26.0, target_hz=22.0, outdoor_temp=8.0)
    # Erlerntes Minimum wurde für diese Zone zurückgesetzt
    assert s.learned_min_hz == regelung.DEFAULT_MIN_HZ_MAP[OUTDOOR_BIN_NORMAL]


def test_user_trigger_resets_learned_min_hz_on_setpoint_change():
    """Säule 2: Ändert der Nutzer den Setpoint, wird das gelernte Minimum zurückgesetzt."""
    s = State()
    s.learned_min_table[OUTDOOR_BIN_NORMAL] = 26.0
    s.last_setpoint = 21.0
    p = Params()
    # Setpoint ändert sich auf 22.0
    step(p, s, setpoint=22.0, hz=26.0, target_hz=30.0, outdoor_temp=8.0)
    assert s.learned_min_hz == regelung.DEFAULT_MIN_HZ_MAP[OUTDOOR_BIN_NORMAL]


def test_weather_delta_trigger_resets_learned_min_hz():
    """Säule 3: Bei einer Außentemperaturänderung >= 5K wird das gelernte Minimum re-validiert."""
    s = State()
    s.learned_min_table[OUTDOOR_BIN_NORMAL] = 26.0
    s.last_outdoor_temp_learned = 8.0
    p = Params(weather_trigger_delta_k=5.0)
    # Außentemperatur springt um 5.5 K (8.0 -> 2.5 °C, immer noch bin 'normal')
    step(p, s, setpoint=21.0, hz=26.0, target_hz=30.0, outdoor_temp=2.5)
    assert s.learned_min_hz == regelung.DEFAULT_MIN_HZ_MAP[OUTDOOR_BIN_NORMAL]


def test_soft_probing_decreases_min_hz_after_interval():
    """Säule 4: Läuft die Anlage stabil auf Mindestmodulation, wird nach 240min vorsichtig 1 Hz tiefer getestet."""
    s = State()
    s.learned_min_table[OUTDOOR_BIN_NORMAL] = 25.0
    s.output = 20.9
    p = Params(probe_interval_min=240.0, interval_s=60.0)
    # 240 min im Mindestmodulationsmodus (14400s)
    s.min_mod_steady_seconds = 240.0 * 60.0
    step(p, s, setpoint=21.0, hz=25.0, target_hz=20.0, outdoor_temp=8.0)
    # Erlernte Mindest-Hz wurde um 1 Hz abgesenkt zum Antasten
    assert s.learned_min_hz == 24.0
    assert s.min_mod_steady_seconds == 0.0


def test_user_trigger_keeps_learned_min_hz_when_new_target_is_above_it():
    """Ein neues Ziel oberhalb des gelernten Minimums entwertet es nicht (PV-Logik)."""
    s = State()
    s.learned_min_table[OUTDOOR_BIN_NORMAL] = 26.0
    s.last_target_hz = 22.0
    p = Params()
    # Ziel springt von 22 auf 40 Hz, das gelernte Minimum (26 Hz) bleibt gültig
    step(p, s, setpoint=21.0, hz=26.0, target_hz=40.0, outdoor_temp=8.0)
    assert s.learned_min_hz == 26.0


def _ff_state(output=20.7, last_target=30.0, sensitivity=15.0):
    """Eingeschwungener Regler (Ausgabe gesetzt), Ziel zuletzt bei last_target."""
    s = State()
    s.output = output
    s.last_target_hz = last_target
    s.last_setpoint = 21.0
    s.learned_sensitivity = sensitivity
    return s


def test_feed_forward_moves_output_on_large_target_increase():
    """Großer Zielsprung nach oben: Ausgang sofort um 60 % der erwarteten Strecke kälter."""
    s = _ff_state()
    p = Params()
    # Fehler 16 Hz / 15 Hz je K * 0,6 = 0,64 K -> 20,7 - 0,64 = 20,06 -> 20,1
    res = step(p, s, setpoint=21.0, hz=30.0, target_hz=46.0, outdoor_temp=8.0)
    assert res.published == 20.1
    # Danach wird die Reaktion der Anlage abgewartet, kein weiterer Schritt im selben Takt
    assert s.time_since_last_step == 0.0


def test_feed_forward_moves_output_on_large_target_decrease():
    s = _ff_state(output=20.0, last_target=46.0)
    p = Params()
    # Fehler -16 Hz -> 0,64 K wärmer: 20,0 + 0,64 = 20,64 -> 20,6
    res = step(p, s, setpoint=21.0, hz=46.0, target_hz=30.0, outdoor_temp=8.0)
    assert res.published == 20.6


def test_feed_forward_is_limited_to_one_kelvin():
    s = _ff_state(sensitivity=6.0)
    p = Params()
    # Rechnerisch 60 Hz / 6 * 0,6 = 6 K -> begrenzt auf 1,0 K
    res = step(p, s, setpoint=21.0, hz=20.0, target_hz=80.0, outdoor_temp=8.0)
    assert res.published == 19.7


def test_no_feed_forward_for_small_target_change():
    """Zielsprünge unter 4 Hz regelt der normale Schrittbetrieb (0,1 K)."""
    s = _ff_state()
    p = Params()
    res = step(p, s, setpoint=21.0, hz=30.0, target_hz=33.0, outdoor_temp=8.0)
    assert res.published == 20.6


def test_no_feed_forward_when_error_within_two_deadbands():
    """Hat die Frequenz das neue Ziel praktisch schon erreicht, bleibt der Ausgang."""
    s = _ff_state()
    p = Params()
    res = step(p, s, setpoint=21.0, hz=33.0, target_hz=35.0, outdoor_temp=8.0)
    assert res.published == 20.7


def test_no_feed_forward_when_compressor_already_accelerating():
    """Läuft der Kompressor schon kräftig in Zielrichtung, wird nicht zusätzlich angeschoben."""
    s = _ff_state()
    s.hz_prev1 = 20.0
    p = Params()
    res = step(p, s, setpoint=21.0, hz=28.0, target_hz=46.0, outdoor_temp=8.0)
    assert res.published == 20.7


def test_no_feed_forward_during_defrost():
    s = _ff_state()
    p = Params()
    res = step(p, s, setpoint=21.0, hz=30.0, target_hz=46.0, outdoor_temp=8.0, defrost=True)
    assert res.mode == MODE_DEFROST
    assert res.published == 20.7


def test_no_feed_forward_without_previous_output():
    """Erststart: der Basis-Ausgangswert kommt aus der Lerntabelle, nicht aus der Vorsteuerung."""
    s = State()
    s.last_target_hz = 30.0
    p = Params()
    res = step(p, s, setpoint=21.0, hz=30.0, target_hz=46.0, outdoor_temp=8.0)
    # 46 Hz -> Bin mid_high (normal: 0,50 K) -> 20,5
    assert res.published == 20.5


def test_feed_forward_respects_safe_hold_offset_below_min_modulation():
    """Ziel unter der Mindestmodulation: Vorsteuerung nie wärmer als der sichere Halte-Offset."""
    p = Params(min_hz_normal=24.0)
    s = _ff_state(output=20.0, last_target=48.0)
    s.learned_min_table[OUTDOOR_BIN_NORMAL] = 24.0
    s.learned_min_offset_table[OUTDOOR_BIN_NORMAL] = 0.4
    # Rechnerisch 20,0 + 0,96 = 20,96, gedeckelt bei 21,0 - (0,4 - 0,1) = 20,7
    res = step(p, s, setpoint=21.0, hz=48.0, target_hz=20.0, outdoor_temp=8.0)
    assert res.published == 20.7


def test_feed_forward_does_not_feed_learning_of_step_response():
    """Die große Vorsteuerung darf nicht als 0,1-K-Schritt die Verstärkung verfälschen."""
    s = _ff_state()
    s.last_step_delta = -0.1
    s.hz_at_last_step = 28.0
    p = Params()
    step(p, s, setpoint=21.0, hz=30.0, target_hz=46.0, outdoor_temp=8.0)
    assert s.last_step_delta == 0.0
    assert s.hz_at_last_step is None


def test_reset_observation_clears_dynamics_but_keeps_learned_values():
    """Nach Pause/Aus/Störung: Beobachtungen weg, Gelerntes und letzte Ausgabe bleiben."""
    s = State()
    s.output = 20.5
    s.learned_sensitivity = 22.0
    s.learned_reaction_time = 100.0
    s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] = 0.7
    s.last_step_delta = -0.1
    s.hz_at_last_step = 25.0
    s.hz_prev1, s.hz_prev2, s.trend = 24.0, 23.0, 3.0
    s.was_defrosting = True
    s.post_defrost_remaining = 120.0
    s.last_running_hz = 30.0

    s.reset_observation()

    assert s.last_step_delta == 0.0 and s.hz_at_last_step is None
    assert s.hz_prev1 is None and s.hz_prev2 is None and s.trend == 0.0
    assert s.was_defrosting is False and s.post_defrost_remaining == 0.0
    assert s.last_running_hz is None
    assert s.output == 20.5
    assert s.learned_sensitivity == 22.0 and s.learned_reaction_time == 100.0
    assert s.learned_table[OUTDOOR_BIN_NORMAL][FREQ_BIN_MID_LOW] == 0.7


def test_stale_step_observation_does_not_corrupt_gain_after_pause():
    """Ohne Reset würde das Wiederanlaufen (25 -> 45 Hz) als Reaktion auf einen alten
    0,1-K-Schritt gelernt und die Verstärkung von 15 auf ca. 43 Hz/K getrieben."""
    s = State()
    s.output = 20.5
    s.time_since_last_step = 20.0
    s.last_step_delta = -0.1
    s.hz_at_last_step = 25.0
    p = Params()

    s.reset_observation()  # Pause/Aus
    step(p, s, setpoint=21.0, hz=45.0, target_hz=46.0, outdoor_temp=8.0)

    assert s.learned_sensitivity == 15.0
    assert s.learned_reaction_time == 90.0


def test_reset_observation_cancels_post_defrost_hold():
    """Wurde während der Abtauung ausgeschaltet, gibt es nach dem Einschalten keine Haltephase."""
    s = State()
    s.output = 20.5
    s.was_defrosting = True
    s.post_defrost_remaining = 120.0
    s.reset_observation()
    res = step(Params(), s, setpoint=21.0, hz=30.0, target_hz=30.0, outdoor_temp=8.0)
    assert res.mode != MODE_POST_DEFROST

