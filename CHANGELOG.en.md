# Changelog

## 2.5.1

### Fixed
* **Wrongly learned minimum modulation (e.g. 120 Hz):** The stagnation detection mistook a high frequency for the minimum modulation when the compressor did not respond to the sensor. This happens, for example, when the controller starts while another indoor unit holds the frequency up. The controller then kept the "minimum" of 119.7 Hz and ran at full load for about an hour. Two causes are fixed:
  * It now only learns if the frequency is at most `min(60 Hz, effective target + 10 Hz)`. If the compressor runs far above that (start-up, defrost, another indoor unit), it is not the minimum modulation.
  * The stagnation now counts real time (at least 180 s or 2 × reaction time) instead of ticks. Event-driven extra ticks (e.g. when the climate entity is switched on) used to count like full one-minute ticks, so the AC counted as "stagnating" after 72 s instead of 3 minutes, before it could even react to the sensor.
* The stagnation time is reset on pause, off and fault (`State.reset_observation()`).

### Tests
* 4 new tests (replay of the incident, real time instead of ticks, normal operation still learns after 3 one-minute ticks, reset of the stagnation time).

### Internal
* `step()` optionally accepts `dt_s` (real time since the last step). The controller supplies it from the monotonic clock (capped at 5 cycles, 0 after pause/start).
* Version in `manifest.json` and in the card set to 2.5.1.

## 2.5.0

Changes compared to 2.4.5. Learned values are kept on update, there are no new options.

### New
* **Feed-forward on large target jumps:** If the target frequency changes by at least 4 Hz, the controller immediately shifts the sensor value by 60 % of the distance expected from the learned gain (at most 1.0 K). The normal control loop trims the rest in small steps. This shortens settling after large jumps (about 1 to 6 minutes in the plant model).
  * Does not act for errors below 4 Hz, during defrost and the post-defrost phase, with a stopped compressor, on first start without an output value, and when the compressor is already accelerating strongly towards the target.
  * If the target is below the minimum modulation, it never goes warmer than the safe hold offset.
  * The jump is not counted as a single step in the learned gain.
  * Constants in the code (`regelung.py`): `FF_GAIN` (0.6), `FF_MAX_K` (1.0), `FF_MIN_JUMP_HZ` (4.0).

### Changed
* **Learned minimum Hz on target change:** The minimum is now only discarded if the new target is *below* the learned minimum. A target above it (e.g. changing targets from PV logic) leaves it untouched, so the AC is no longer released for re-testing on every change. A change of the setpoint still resets it as before.

### Fixed
* **Stale step observation after pause, off or fault:** When switching off (or when the AC is not heating, or after the fault timeout), the observation of the last step stayed behind. After switching on again, the frequency change from the restart was counted as the reaction to that old step and the learned gain was learned wrongly (example: 15 → about 43 Hz/K). Observation, trend, frequency history, defrost flags and last running frequency are now reset (`State.reset_observation()`). Learned values and the last output are kept.

### Documentation
* README (de/en): The target frequency entity accepts 10 to 120 Hz, only the card limits it downwards; below the minimum modulation the controller regulates to it internally.
* README (de/en): Without a real room sensor, the overheat protection uses `current_temperature` of the climate entity. If it reports the simulated value (e.g. ProtoArt), it cannot detect real overheating. The room sensor is now also listed for the restart hold.
* README (de/en): The control cycle (60 s) and the fault timeout (10 min) are fixed presets.
* Docstring `regelung.py`: 5 instead of 4 pillars, matching the README.

### Tests
* 14 new core tests (feed-forward, minimum Hz rule, reset of the observation), 1 new Home Assistant test (pause discards the step observation).
* One existing test (`test_probing_and_reset_respect_configured_zone_floor`) was adapted to the new minimum Hz rule.

### Internal
* Version in `manifest.json` and in the card (`ac-pid-frequency-card.js`) set to 2.5.0.
