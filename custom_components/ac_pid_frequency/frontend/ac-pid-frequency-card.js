/*
 * AC PID Frequency – Lovelace-Karte
 *
 * Sieht aus und bedient sich wie die Thermostat-Karte von Home Assistant, zeigt zusätzlich
 * die Kompressor-Ist-Frequenz und bietet ein Eingabefeld mit +/- für die Ziel-Frequenz.
 * Wird von der Integration "ac_pid_frequency" automatisch ausgeliefert und geladen.
 *
 * Minimale Konfiguration:
 *   type: custom:ac-pid-frequency-card
 *   entity: climate.mein_master_innengeraet
 *
 * Optional:
 *   name: Wohnzimmer
 *   controller: sensor.<status-sensor>   # nur nötig, wenn die automatische Suche scheitert
 *   show_units: false                    # weitere Innengeräte ausblenden
 */

const HZ_CARD_VERSION = "2.4.4";

const HZ_I18N = {
  de: {
    modes: {
      off: "Aus", heat: "Heizen", cool: "Kühlen", auto: "Auto", heat_cool: "Heizen/Kühlen",
      dry: "Entfeuchten", fan_only: "Lüfter",
    },
    actions: {
      heating: "Heizt", cooling: "Kühlt", idle: "Bereit", off: "Aus", drying: "Entfeuchtet",
      fan: "Lüfter", defrosting: "Abtauen", preheating: "Vorheizen",
    },
    status: {
      off: "Regler aus", idle: "Wartet (kein Heizbetrieb)", raise: "Frequenz erhöhen",
      lower: "Frequenz senken", hold: "Im Zielbereich (stabil)", min_mod: "Mindestmodulation (stabil gehalten)",
      defrost: "Abtauen aktiv (pausiert)", "after-defrost-timer": "Nach-Abtau-Stabilisierung",
      overheat: "Überhitzungsschutz aktiv", waiting: "Daten fehlen – Wert gehalten",
      fault: "Fehler – Anlage nutzt eigenen Sensor",
    },
    unavailable: "Nicht verfügbar", simulated: "Simuliert", real: "Real", outdoor: "Außen", compressor: "Kompressor",
    target_hz: "Ziel-Frequenz", controller: "Hz-Regelung",
    sensor: "Sensor", offset: "Offset", factor: "Faktor", min_hz: "Min", other_units: "Weitere Innengeräte",
    min_hz_label: "Erlernte Mindest-Hz", reset_min: "Reset", reset_min_title: "Erlernte Mindest-Hz verwerfen und neu lernen",
    passthrough: "echte Raumtemperatur durchgereicht",
    more: "Details", minus: "Weniger", plus: "Mehr",
    not_found: "Kein AC-PID-Frequency-Regler für diese Klimaanlage gefunden. Ist die Integration eingerichtet?",
    entity: "Klimaanlage (Master-Innengerät)", name: "Name (optional)",
    controller_entity: "Status-Sensor des Reglers (optional)",
  },
  en: {
    modes: {
      off: "Off", heat: "Heat", cool: "Cool", auto: "Auto", heat_cool: "Heat/Cool",
      dry: "Dry", fan_only: "Fan only",
    },
    actions: {
      heating: "Heating", cooling: "Cooling", idle: "Idle", off: "Off", drying: "Drying",
      fan: "Fan", defrosting: "Defrosting", preheating: "Preheating",
    },
    status: {
      off: "Controller off", idle: "Waiting (not heating)", raise: "Raising frequency",
      lower: "Lowering frequency", hold: "On target (stable)", min_mod: "Minimum modulation (stabilized)",
      defrost: "Defrost active (paused)", "after-defrost-timer": "Post-defrost stabilization",
      overheat: "Overheat protection active", waiting: "Data missing – value held",
      fault: "Fault – AC uses its own sensor",
    },
    unavailable: "Unavailable", simulated: "Simulated", real: "Real", outdoor: "Outdoor", compressor: "Compressor",
    target_hz: "Target frequency", controller: "Frequency control",
    sensor: "Sensor", offset: "Offset", factor: "Factor", min_hz: "Min", other_units: "Other indoor units",
    min_hz_label: "Learned min Hz", reset_min: "Reset", reset_min_title: "Reset learned minimum frequency and re-learn",
    passthrough: "real room temperature passed through",
    more: "Details", minus: "Less", plus: "More",
    not_found: "No AC PID Frequency controller found for this air conditioner. Is the integration set up?",
    entity: "Air conditioner (master indoor unit)", name: "Name (optional)",
    controller_entity: "Controller status sensor (optional)",
  },
};
