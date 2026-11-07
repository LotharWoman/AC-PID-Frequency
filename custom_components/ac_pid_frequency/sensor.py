"""Sensoren: der vorgetäuschte Raumtemperatursensor plus Diagnosewerte."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfFrequency, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CLIMATE,
    CONF_DEFROST,
    CONF_FREQUENCY,
    CONF_INDOOR_UNITS,
    CONF_OUTDOOR_TEMP,
    CONF_ROOM_TEMP,
    DOMAIN,
    STATUSES,
)
from .controller import AcPidFrequencyController
from .entity import AcPidFrequencyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller: AcPidFrequencyController = entry.runtime_data
    async_add_entities(
        [
            FakeTemperatureSensor(controller),
            StatusSensor(controller),
            OffsetSensor(controller),
            FactorSensor(controller),
            ErrorSensor(controller),
            MinHzSensor(controller),
        ]
    )


class FakeTemperatureSensor(AcPidFrequencyEntity, SensorEntity):
    """Der "Raumthermometer"-Wert für die Klimaanlage (0,1-K-Schritte).

    Regelt der Regler nicht (aus / kein Heizbetrieb), wird die echte Raumtemperatur
    durchgereicht, sofern ein Raumsensor konfiguriert ist und einen Wert liefert. Sonst wird
    der Sensor ``unavailable`` und die Anlage fällt auf ihren eigenen Innensensor zurück.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "temperature")

    @property
    def available(self) -> bool:
        return self.controller.available and self.controller.output is not None

    @property
    def native_value(self) -> float | None:
        return self.controller.output


class StatusSensor(AcPidFrequencyEntity, SensorEntity):
    """Reglerstatus; trägt außerdem die Entitäts-IDs, die die Karte zum Finden braucht."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "status")

    @property
    def native_value(self) -> str:
        return self.controller.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        registry = er.async_get(self.hass)
        entry_id = self.controller.entry.entry_id
        cfg = self.controller.config

        def lookup(platform: str, key: str) -> str | None:
            return registry.async_get_entity_id(platform, DOMAIN, f"{entry_id}_{key}")

        return {
            # Schlüssel, über den die Karte "ihren" Regler zur Climate-Entität findet
            "ac_pid_frequency_climate": cfg[CONF_CLIMATE],
            "frequency_entity": cfg[CONF_FREQUENCY],
            "outdoor_temperature_entity": cfg.get(CONF_OUTDOOR_TEMP),
            "room_temperature_entity": cfg.get(CONF_ROOM_TEMP),
            "defrost_entity": cfg.get(CONF_DEFROST),
            "passthrough": self.controller.passthrough,
            "indoor_units": list(cfg.get(CONF_INDOOR_UNITS) or []),
            "active_outdoor_bin": self.controller.regelung.current_outdoor_bin,
            "active_freq_bin": self.controller.regelung.current_freq_bin,
            "learned_offset": self.controller.regelung.current_learned_offset,
            "learned_min_hz": self.controller.regelung.learned_min_hz,
            "learned_reaction_time": self.controller.regelung.learned_reaction_time,
            "learned_sensitivity": self.controller.regelung.learned_sensitivity,
            "effective_target_hz": self.controller.regelung.effective_target_hz,
            "temperature_entity": lookup("sensor", "temperature"),
            "offset_entity": lookup("sensor", "offset"),
            "factor_entity": lookup("sensor", "learning_factor"),
            "error_entity": lookup("sensor", "frequency_error"),
            "min_hz_entity": lookup("sensor", "learned_min_hz"),
            "target_hz_entity": lookup("number", "target_hz"),
            "switch_entity": lookup("switch", "enabled"),
        }


class OffsetSensor(AcPidFrequencyEntity, SensorEntity):
    """Abstand des Sensorwerts zur Soll-Temperatur (positiv = Anlage wird angeschoben)."""

    _attr_native_unit_of_measurement = "K"
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "offset")

    @property
    def native_value(self) -> float | None:
        return self.controller.offset


class FactorSensor(AcPidFrequencyEntity, SensorEntity):
    """Aktueller Erfahrungswert / gelernter Offset für den aktiven Arbeitspunkt."""

    _attr_native_unit_of_measurement = "K"
    _attr_suggested_display_precision = 2
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "learning_factor")

    @property
    def native_value(self) -> float:
        return self.controller.regelung.current_learned_offset


class ErrorSensor(AcPidFrequencyEntity, SensorEntity):
    """Regelabweichung in Hz (Ziel minus Ist)."""

    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_suggested_display_precision = 1
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "frequency_error")

    @property
    def native_value(self) -> float | None:
        return self.controller.error_hz


class MinHzSensor(AcPidFrequencyEntity, SensorEntity):
    """Erreichte bzw. erlernte Mindestmodulation des Kompressors (Hz)."""

    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_suggested_display_precision = 1
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:arrow-collapse-down"

    def __init__(self, controller: AcPidFrequencyController) -> None:
        super().__init__(controller, "learned_min_hz")

    @property
    def native_value(self) -> float:
        return self.controller.regelung.learned_min_hz
