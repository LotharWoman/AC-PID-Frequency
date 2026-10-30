"""Konstanten für AC PID Frequency."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ac_pid_frequency"

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SWITCH, Platform.BUTTON]

# --- Entitäten-Auswahl (Setup + Optionen) -------------------------------------------------
CONF_NAME = "name"
CONF_CLIMATE = "climate_entity"  # Master-Innengerät
CONF_FREQUENCY = "frequency_entity"  # Kompressor-Hz als Zahl
CONF_INDOOR_UNITS = "indoor_units"  # weitere Innengeräte (nur Anzeige)

# --- Regel-Parameter (nur Optionen) -------------------------------------------------------
CONF_INTERVAL = "interval_s"
CONF_FAULT_TIMEOUT = "fault_timeout_min"
CONF_DEADBAND = "deadband_hz"
CONF_OFFSET_RAISE = "offset_raise"
CONF_OFFSET_LOWER = "offset_lower"
CONF_OFFSET_BRAKE = "offset_brake"
CONF_HOLD_LIMIT = "hold_limit"
CONF_STEP_RAISE = "step_raise"
CONF_STEP_NORMAL = "step_normal"
CONF_MAX_OFFSET = "max_offset"
CONF_HUNTING = "hunting_hz"
CONF_FACTOR_MIN = "factor_min"
CONF_FACTOR_MAX = "factor_max"
CONF_FACTOR_FLOOR = "factor_floor"
CONF_FACTOR_DOWN = "factor_down"
CONF_FACTOR_UP = "factor_up"

DEFAULT_NAME = "AC PID Frequency"
DEFAULT_FAULT_TIMEOUT_MIN = 10

# Standardwerte der Regel-Parameter = Werte der bewährten YAML (v8.1)
TUNING_DEFAULTS: dict[str, float] = {
    CONF_INTERVAL: 60,
    CONF_FAULT_TIMEOUT: DEFAULT_FAULT_TIMEOUT_MIN,
    CONF_DEADBAND: 3.0,
    CONF_OFFSET_RAISE: 0.6,
    CONF_OFFSET_LOWER: 0.4,
    CONF_OFFSET_BRAKE: 0.5,
    CONF_HOLD_LIMIT: 0.3,
    CONF_STEP_RAISE: 0.1,
    CONF_STEP_NORMAL: 0.08,
    CONF_MAX_OFFSET: 1.0,
    CONF_HUNTING: 2.0,
    CONF_FACTOR_MIN: 0.6,
    CONF_FACTOR_MAX: 1.2,
    CONF_FACTOR_FLOOR: 0.8,
    CONF_FACTOR_DOWN: 0.1,
    CONF_FACTOR_UP: 0.05,
}

# --- Laufzeitwerte (per Entität änderbar, im Store gespeichert) ---------------------------
DEFAULT_TARGET_HZ = 30
DEFAULT_BRAKE_HZ = 70
TARGET_HZ_MIN, TARGET_HZ_MAX = 10, 120
BRAKE_HZ_MIN, BRAKE_HZ_MAX = 20, 120

# --- Regler-Status ------------------------------------------------------------------------
STATUS_OFF = "off"  # Regler ausgeschaltet
STATUS_IDLE = "idle"  # Anlage nicht im Heizbetrieb
STATUS_WAITING = "waiting"  # Eingangsdaten fehlen, letzter Wert wird gehalten
STATUS_FAULT = "fault"  # Eingangsdaten fehlen zu lange, Sensor ist unavailable
# plus die Regelmodi aus regelung.py: raise / lower / hold / brake
STATUSES = [
    STATUS_OFF,
    STATUS_IDLE,
    "raise",
    "lower",
    "hold",
    "brake",
    STATUS_WAITING,
    STATUS_FAULT,
]

HVAC_MODE_ACTIVE = "heat"  # erstmal nur Heizen

STORAGE_VERSION = 1

# --- Frontend -----------------------------------------------------------------------------
CARD_FILE = "ac-pid-frequency-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"
