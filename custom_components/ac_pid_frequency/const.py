"""Konstanten für AC PID Frequency."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ac_pid_frequency"

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.SWITCH, Platform.BUTTON]

# --- Entitäten-Auswahl (Setup + Optionen) -------------------------------------------------
CONF_NAME = "name"
CONF_CLIMATE = "climate_entity"  # Master-Innengerät
CONF_FREQUENCY = "frequency_entity"  # Kompressor-Hz als Zahl
CONF_OUTDOOR_TEMP = "outdoor_temp_entity"  # Außentemperatur (optional: sensor oder weather)
CONF_ROOM_TEMP = "room_temp_entity"  # Echter Raumtemperatursensor (optional)
CONF_DEFROST = "defrost_entity"  # Abtau-Sensor (optional: binary_sensor oder sensor)
CONF_INDOOR_UNITS = "indoor_units"  # weitere Innengeräte (nur Anzeige)

# --- Regel-Parameter (nur Optionen) -------------------------------------------------------
CONF_INTERVAL = "interval_s"
CONF_REACTION_TIME = "reaction_time_s"
CONF_FAULT_TIMEOUT = "fault_timeout_min"
CONF_DEADBAND = "deadband_hz"
CONF_OFFSET_BRAKE = "offset_brake"
CONF_MAX_OFFSET = "max_offset"
CONF_MAX_ROOM_OVERHEAT = "max_room_overheat"

DEFAULT_NAME = "AC PID Frequency"
DEFAULT_FAULT_TIMEOUT_MIN = 10

# Standardwerte der Regel-Parameter
TUNING_DEFAULTS: dict[str, float] = {
    CONF_INTERVAL: 60.0,
    CONF_REACTION_TIME: 120.0,
    CONF_FAULT_TIMEOUT: DEFAULT_FAULT_TIMEOUT_MIN,
    CONF_DEADBAND: 3.0,
    CONF_OFFSET_BRAKE: 0.5,
    CONF_MAX_OFFSET: 1.0,
    CONF_MAX_ROOM_OVERHEAT: 1.0,
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
STATUS_DEFROST = "defrost"  # Abtauen aktiv, Regelung und Lernen pausiert
STATUS_OVERHEAT = "overheat"  # Raum überhitzt, thermische Bremse aktiv

STATUSES = [
    STATUS_OFF,
    STATUS_IDLE,
    "raise",
    "lower",
    "hold",
    "brake",
    STATUS_DEFROST,
    STATUS_OVERHEAT,
    STATUS_WAITING,
    STATUS_FAULT,
]

HVAC_MODE_ACTIVE = "heat"  # Heizen

STORAGE_VERSION = 1

# --- Frontend -----------------------------------------------------------------------------
CARD_FILE = "ac-pid-frequency-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"
