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

const HZ_CARD_VERSION = "2.4.3";

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
      defrost: "Abtauen aktiv (pausiert)", overheat: "Überhitzungsschutz aktiv",
      waiting: "Daten fehlen – Wert gehalten", fault: "Fehler – Anlage nutzt eigenen Sensor",
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
      defrost: "Defrost active (paused)", overheat: "Overheat protection active",
      waiting: "Data missing – value held", fault: "Fault – AC uses its own sensor",
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

const HZ_MODE_ICONS = {
  off: "mdi:power", heat: "mdi:fire", cool: "mdi:snowflake", auto: "mdi:thermostat-auto",
  heat_cool: "mdi:sun-snowflake-variant", dry: "mdi:water-percent", fan_only: "mdi:fan",
};

const HZ_MODE_COLORS = {
  heat: "var(--state-climate-heat-color, #ff8100)",
  cool: "var(--state-climate-cool-color, #2b9af9)",
  heat_cool: "var(--state-climate-heat_cool-color, #43a047)",
  auto: "var(--state-climate-auto-color, #43a047)",
  dry: "var(--state-climate-dry-color, #efbd07)",
  fan_only: "var(--state-climate-fan_only-color, #8a8a8a)",
  off: "var(--state-climate-off-color, var(--disabled-color, #bdbdbd))",
};

// Ziffernblatt: 270°-Bogen, Öffnung unten
const DIAL = { cx: 100, cy: 100, r: 86, start: 135, sweep: 270 };

const HZ_STYLE = `
  :host { display: block; }
  ha-card { padding: 0; overflow: hidden; --mode-color: var(--disabled-color, #bdbdbd); }
  .wrap { padding: 8px 16px 16px; display: flex; flex-direction: column; gap: 14px; }
  .unavail { opacity: .55; pointer-events: none; }

  .header { display: flex; align-items: center; justify-content: space-between; min-height: 40px; }
  .title { font-size: 18px; font-weight: 500; color: var(--primary-text-color); overflow: hidden;
           text-overflow: ellipsis; white-space: nowrap; padding-top: 6px; }
  .icon-btn { background: none; border: none; cursor: pointer; padding: 8px; border-radius: 50%;
              color: var(--secondary-text-color); display: inline-flex; --mdc-icon-size: 22px; }
  .icon-btn:hover { background: var(--secondary-background-color, rgba(127,127,127,.15)); }

  .dial-wrap { position: relative; width: 100%; max-width: 250px; margin: 0 auto; aspect-ratio: 200 / 172; }
  svg.dial { width: 100%; height: 100%; touch-action: none; cursor: pointer; display: block; }
  .track { fill: none; stroke: var(--divider-color, rgba(127,127,127,.35)); stroke-width: 14; stroke-linecap: round; }
  .fill { fill: none; stroke: var(--mode-color); stroke-width: 14; stroke-linecap: round; transition: stroke .3s; }
  .knob { fill: var(--card-background-color, #fff); stroke: var(--mode-color); stroke-width: 3; }
  .cur-mark { stroke: var(--primary-text-color); stroke-width: 3; stroke-linecap: round; opacity: .55; }
  .dial-center { position: absolute; inset: 0 0 -16.3% 0; display: flex; flex-direction: column; align-items: center;
                 justify-content: center; pointer-events: none; text-align: center; gap: 2px; }
  .action { font-size: 13px; letter-spacing: .02em; color: var(--mode-color); font-weight: 500; min-height: 18px; }
  .target { color: var(--primary-text-color); line-height: 1; display: flex; align-items: flex-start; }
  .target .int { font-size: 54px; font-weight: 400; }
  .target .dec { font-size: 26px; margin-top: 6px; }
  .target .unit { font-size: 20px; margin-top: 6px; margin-left: 2px; color: var(--secondary-text-color); }
  .current { font-size: 14px; color: var(--secondary-text-color); margin-top: 4px; }
  .current + .current { margin-top: 0; }
  .current:empty { display: none; }

  .pm { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; margin-top: -2px; }
  .pm-btns { display: flex; gap: 28px; }
  .outdoor { justify-self: end; text-align: right; line-height: 1.25; color: var(--secondary-text-color); font-size: 12px; }
  .outdoor b { display: block; font-size: 15px; font-weight: 500; color: var(--primary-text-color); }
  button.round { width: 48px; height: 48px; border-radius: 50%; border: 1px solid var(--divider-color, #ccc);
                 background: none; cursor: pointer; color: var(--primary-text-color); display: inline-flex;
                 align-items: center; justify-content: center; --mdc-icon-size: 24px; padding: 0; }
  button.round:hover { background: var(--secondary-background-color, rgba(127,127,127,.15)); }
  button.round:active { transform: scale(.94); }
  button.round.small { width: 34px; height: 34px; flex: none; --mdc-icon-size: 20px; }

  .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .tile { background: var(--secondary-background-color, rgba(127,127,127,.1)); border-radius: 14px;
          padding: 10px 10px 12px 12px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .tile .label { font-size: 12px; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .04em; }
  .hz-big { font-size: 30px; line-height: 1.1; color: var(--primary-text-color); }
  .hz-big small, .stepper .u { font-size: 13px; color: var(--secondary-text-color); margin-left: 2px; }
  .bar { position: relative; height: 6px; border-radius: 3px; background: var(--divider-color, rgba(127,127,127,.35)); margin-top: 4px; }
  .bar .b-fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px; background: var(--mode-color); transition: width .5s; }
  .bar .mark { position: absolute; top: -3px; bottom: -3px; width: 2px; border-radius: 1px; }
  .bar .mark.t { background: var(--primary-text-color); }
  .legend { display: flex; gap: 10px; font-size: 11px; color: var(--secondary-text-color); }
  .legend i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 4px; }

  .stepper { display: flex; align-items: center; justify-content: space-between; gap: 4px; min-width: 0; }
  .stepper .field { display: flex; align-items: baseline; justify-content: center; flex: 1 1 auto; min-width: 0; white-space: nowrap; }
  .stepper input { width: 2.2em; min-width: 0; font-size: 24px; text-align: center; background: transparent; border: none;
                   border-bottom: 1px solid var(--divider-color, #ccc); color: var(--primary-text-color);
                   font-family: inherit; padding: 0; -moz-appearance: textfield; appearance: textfield; }
  .stepper input:focus { outline: none; border-bottom-color: var(--mode-color); }
  .stepper input::-webkit-outer-spin-button, .stepper input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }

  .regler { background: var(--secondary-background-color, rgba(127,127,127,.1)); border-radius: 14px;
            padding: 10px 12px; display: flex; flex-direction: column; gap: 10px; }
  .regler .row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .regler .name { display: flex; align-items: center; gap: 8px; color: var(--primary-text-color); font-weight: 500; }
  .regler .name ha-icon { color: var(--mode-color); --mdc-icon-size: 22px; }
  .status { font-size: 13px; color: var(--secondary-text-color); }
  .status.warn { color: var(--warning-color, #f4b400); }
  .status.err { color: var(--error-color, #db4437); }
  .detail { font-size: 12px; color: var(--secondary-text-color); }
  .min-hz-row { display: flex; align-items: center; justify-content: space-between; gap: 8px;
                padding-top: 8px; border-top: 1px solid var(--divider-color, rgba(127,127,127,.2)); }
  .min-hz-info { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--secondary-text-color); }
  .min-hz-info ha-icon { --mdc-icon-size: 20px; color: var(--mode-color); }
  .min-hz-info b { color: var(--primary-text-color); font-weight: 500; }
  .reset-btn { background: var(--secondary-background-color, rgba(127,127,127,.15)); border: 1px solid var(--divider-color, rgba(127,127,127,.25));
               border-radius: 8px; padding: 4px 10px; font-size: 12px; font-family: inherit;
               color: var(--primary-text-color); cursor: pointer; display: inline-flex; align-items: center;
               gap: 6px; transition: background .15s, transform .1s; }
  .reset-btn ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
  .reset-btn:hover { background: var(--secondary-background-color, rgba(127,127,127,.3)); }
  .reset-btn:active { transform: scale(.96); }
  .reset-btn:disabled { opacity: .4; cursor: default; }
  .toggle { width: 46px; height: 26px; border-radius: 13px; border: none; padding: 0; cursor: pointer; position: relative;
            background: var(--switch-unchecked-track-color, rgba(127,127,127,.5)); transition: background .2s; flex: none; }
  .toggle::after { content: ""; position: absolute; top: 3px; left: 3px; width: 20px; height: 20px; border-radius: 50%;
                   background: var(--switch-unchecked-button-color, #fff); transition: transform .2s; box-shadow: 0 1px 3px rgba(0,0,0,.4); }
  .toggle.on { background: var(--mode-color); }
  .toggle.on::after { transform: translateX(20px); }

  .modes { display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
  .modes button { width: 46px; height: 46px; border-radius: 50%; border: none; cursor: pointer; --mdc-icon-size: 24px;
                  background: var(--secondary-background-color, rgba(127,127,127,.15)); color: var(--secondary-text-color);
                  display: inline-flex; align-items: center; justify-content: center; padding: 0; }
  .modes button.active { background: var(--btn-color); color: var(--text-primary-color, #fff); }

  .units { display: flex; flex-direction: column; gap: 4px; }
  .units .cap { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--secondary-text-color); }
  .units .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { font-size: 12px; padding: 4px 10px; border-radius: 12px; color: var(--secondary-text-color);
          background: var(--secondary-background-color, rgba(127,127,127,.12)); display: inline-flex; gap: 6px; align-items: center;
          border: none; cursor: pointer; font-family: inherit; transition: background .15s, transform .1s, color .15s; }
  .chip:hover { background: var(--secondary-background-color, rgba(127,127,127,.25)); color: var(--primary-text-color); }
  .chip:active { transform: scale(0.97); }
  .chip b { color: var(--primary-text-color); font-weight: 500; }
  .notice { font-size: 13px; color: var(--warning-color, #f4b400); background: var(--secondary-background-color);
            border-radius: 10px; padding: 8px 10px; }
`;

const HZ_TEMPLATE = `
  <ha-card id="card">
    <div class="wrap" id="wrap">
      <div class="header">
        <div class="title" id="title"></div>
        <button class="icon-btn" id="more" aria-label="Details"><ha-icon icon="mdi:dots-vertical"></ha-icon></button>
      </div>

      <div class="dial-wrap">
        <svg class="dial" id="dial" viewBox="0 0 200 172">
          <path class="track" id="track"></path>
          <path class="fill" id="fill"></path>
          <line class="cur-mark" id="curmark"></line>
          <circle class="knob" id="knob" r="9"></circle>
        </svg>
        <div class="dial-center">
          <div class="action" id="action"></div>
          <div class="target"><span class="int" id="t-int">–</span><span class="dec" id="t-dec"></span><span class="unit" id="t-unit"></span></div>
          <div class="current" id="current"></div>
          <div class="current" id="real"></div>
        </div>
      </div>

      <div class="pm">
        <span></span>
        <div class="pm-btns">
          <button class="round" id="t-minus" aria-label="-"><ha-icon icon="mdi:minus"></ha-icon></button>
          <button class="round" id="t-plus" aria-label="+"><ha-icon icon="mdi:plus"></ha-icon></button>
        </div>
        <span class="outdoor" id="outdoor" hidden></span>
      </div>

      <div id="hz-section">
        <div class="tiles">
          <div class="tile">
            <div class="label" id="l-comp"></div>
            <div class="hz-big"><span id="hz-val">–</span><small>Hz</small></div>
            <div class="bar">
              <div class="b-fill" id="bar-fill"></div>
              <div class="mark t" id="mark-t"></div>
            </div>
          </div>
          <div class="tile">
            <div class="label" id="l-target"></div>
            <div class="stepper">
              <button class="round small" id="hz-minus" aria-label="-"><ha-icon icon="mdi:minus"></ha-icon></button>
              <div class="field"><input id="hz-in" type="number" inputmode="decimal" step="1"><span class="u">Hz</span></div>
              <button class="round small" id="hz-plus" aria-label="+"><ha-icon icon="mdi:plus"></ha-icon></button>
            </div>
          </div>
        </div>
      </div>

      <div class="regler" id="regler">
        <div class="row">
          <div>
            <div class="name"><ha-icon icon="mdi:thermostat-auto"></ha-icon><span id="l-ctrl"></span></div>
            <div class="status" id="status"></div>
          </div>
          <button class="toggle" id="toggle" role="switch" aria-checked="false"></button>
        </div>
        <div class="detail" id="detail"></div>
        <div class="min-hz-row" id="min-hz-row" hidden>
          <div class="min-hz-info">
            <ha-icon icon="mdi:arrow-collapse-down"></ha-icon>
            <span id="l-min-hz-desc"></span>: <b id="min-hz-val">–</b>
          </div>
          <button class="reset-btn" id="reset-min-hz" type="button">
            <ha-icon icon="mdi:restore"></ha-icon>
            <span id="l-reset-min"></span>
          </button>
        </div>
      </div>
      <div class="notice" id="notice" hidden></div>

      <div class="modes" id="modes"></div>
      <div class="units" id="units" hidden><div class="cap" id="l-units"></div><div class="chips" id="chips"></div></div>
    </div>
  </ha-card>
`;

class AcPidFrequencyCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("ac-pid-frequency-card-editor");
  }

  static getStubConfig(hass) {
    const climate = Object.keys((hass && hass.states) || {}).find((e) => e.startsWith("climate."));
    return { entity: climate || "climate.example" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pending = {};
    this._timers = {};
    this._modesSig = "";
    this._unitsSig = "";
    this._ctrlId = null;
    this._dragging = false;
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Bitte 'entity' (Climate-Entität des Master-Innengeräts) angeben.");
    }
    this._config = { show_units: true, ...config };
    this._ctrlId = null;
    if (!this._built) this._build();
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._built && this._config) this._update();
  }

  getCardSize() {
    return 10;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  // ------------------------------------------------------------------------ Aufbau
  _build() {
    this.shadowRoot.innerHTML = `<style>${HZ_STYLE}</style>${HZ_TEMPLATE}`;
    this._built = true;
    const $ = (id) => this.shadowRoot.getElementById(id);
    this.$ = $;

    $("track").setAttribute("d", this._arc(DIAL.start, DIAL.start + DIAL.sweep));

    $("more").addEventListener("click", () => this._moreInfo(this._config.entity));

    // Solltemperatur: Buttons
    $("t-minus").addEventListener("click", () => this._bumpTemp(-1));
    $("t-plus").addEventListener("click", () => this._bumpTemp(1));

    // Solltemperatur: Ziffernblatt ziehen
    const dial = $("dial");
    dial.addEventListener("pointerdown", (ev) => {
      this._dragging = true;
      dial.setPointerCapture(ev.pointerId);
      this._dragTo(ev);
    });
    dial.addEventListener("pointermove", (ev) => {
      if (this._dragging) this._dragTo(ev);
    });
    const endDrag = () => {
      if (!this._dragging) return;
      this._dragging = false;
      this._commit("temp");
    };
    dial.addEventListener("pointerup", endDrag);
    dial.addEventListener("pointercancel", endDrag);

    // Ziel-Hz
    $("hz-minus").addEventListener("click", () => this._bumpNumber("hz", -1));
    $("hz-plus").addEventListener("click", () => this._bumpNumber("hz", 1));
    const input = $("hz-in");
    input.addEventListener("change", () => {
      const value = parseFloat(String(input.value).replace(",", "."));
      if (Number.isFinite(value)) {
        this._pending["hz"] = this._clampNumber("hz", value);
        this._commit("hz", 0);
      }
      this._update();
    });
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") input.blur();
    });

    // Regler an/aus
    $("toggle").addEventListener("click", () => {
      const ctrl = this._ctrl();
      const sw = ctrl && this._hass.states[ctrl.attributes.switch_entity];
      if (!sw) return;
      this._hass.callService("switch", sw.state === "on" ? "turn_off" : "turn_on", {
        entity_id: sw.entity_id,
      });
    });

    // Mindest-Hz Reset
    $("reset-min-hz").addEventListener("click", () => {
      const ctrl = this._ctrl();
      const btnId = ctrl && ctrl.attributes.reset_min_hz_button_entity;
      if (!btnId) return;
      this._hass.callService("button", "press", { entity_id: btnId });
    });
  }

  // ------------------------------------------------------------------------ Hilfen
  _t() {
    const lang = ((this._hass && this._hass.language) || "en").slice(0, 2);
    return HZ_I18N[lang] || HZ_I18N.en;
  }

  _fmt(value, digits = 1) {
    const lang = (this._hass && this._hass.language) || "en";
    return Number(value).toLocaleString(lang, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  _num(state) {
    if (!state || state.state === "unavailable" || state.state === "unknown") return null;
    const n = parseFloat(state.state);
    return Number.isFinite(n) ? n : null;
  }

  _moreInfo(entityId) {
    this.dispatchEvent(
      new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } })
    );
  }

  _arc(a0, a1) {
    const pt = (a) => {
      const r = (a * Math.PI) / 180;
      return [DIAL.cx + DIAL.r * Math.cos(r), DIAL.cy + DIAL.r * Math.sin(r)];
    };
    const [x0, y0] = pt(a0);
    const [x1, y1] = pt(a1);
    if (Math.abs(a1 - a0) < 0.5) return "";
    const large = a1 - a0 > 180 ? 1 : 0;
    return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${DIAL.r} ${DIAL.r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  }

  _angleFor(value, min, max) {
    const frac = Math.max(0, Math.min(1, (value - min) / (max - min || 1)));
    return DIAL.start + DIAL.sweep * frac;
  }

  /** Controller (Status-Sensor der Integration) zur konfigurierten Climate-Entität finden. */
  _ctrl() {
    const states = this._hass.states;
    if (this._config.controller) return states[this._config.controller] || null;
    if (this._ctrlId && states[this._ctrlId] &&
        states[this._ctrlId].attributes.ac_pid_frequency_climate === this._config.entity) {
      return states[this._ctrlId];
    }
    this._ctrlId = null;
    for (const id in states) {
      if (id.startsWith("sensor.") && states[id].attributes.ac_pid_frequency_climate === this._config.entity) {
        this._ctrlId = id;
        return states[id];
      }
    }
    return null;
  }

  _tempMeta(climate) {
    const a = climate.attributes;
    const step = Number(a.target_temp_step) || 0.5;
    const min = Number.isFinite(Number(a.min_temp)) ? Number(a.min_temp) : 16;
    const max = Number.isFinite(Number(a.max_temp)) ? Number(a.max_temp) : 30;
    return { step, min, max };
  }

  _numberMeta(key) {
    const ctrl = this._ctrl();
    const id = ctrl && ctrl.attributes["target_hz_entity"];
    const st = id && this._hass.states[id];
    const a = (st && st.attributes) || {};
    let min = Number.isFinite(Number(a.min)) ? Number(a.min) : 0;
    const learnedMin = ctrl && ctrl.attributes && Number(ctrl.attributes.learned_min_hz);
    if (Number.isFinite(learnedMin) && learnedMin > min) {
      min = learnedMin;
    }
    return {
      id,
      state: st,
      min,
      max: Number.isFinite(Number(a.max)) ? Number(a.max) : 120,
      step: Number(a.step) || 1,
    };
  }

  _clampNumber(key, value) {
    const m = this._numberMeta(key);
    const snapped = Math.round(value / m.step) * m.step;
    return Math.max(m.min, Math.min(m.max, snapped));
  }

  // ------------------------------------------------------------------------ Bedienung
  _debounce(key, fn, ms) {
    clearTimeout(this._timers[key]);
    this._timers[key] = setTimeout(fn, ms);
  }

  _bumpTemp(dir) {
    const climate = this._hass.states[this._config.entity];
    if (!climate) return;
    const m = this._tempMeta(climate);
    clearTimeout(this._timers["temp-clear"]);
    const current = Number(climate.attributes.temperature);
    const base = this._pending.temp ?? (Number.isFinite(current) ? current : m.min);
    const next = Math.round((base + dir * m.step) / m.step) * m.step;
    this._pending.temp = Math.max(m.min, Math.min(m.max, Number(next.toFixed(2))));
    this._update();
    this._debounce("temp", () => this._commit("temp", 0), 800);
  }

  _dragTo(ev) {
    const climate = this._hass.states[this._config.entity];
    if (!climate) return;
    const m = this._tempMeta(climate);
    clearTimeout(this._timers["temp-clear"]);
    const rect = this.$("dial").getBoundingClientRect();
    const x = ev.clientX - (rect.left + rect.width / 2);
    const y = ev.clientY - (rect.top + rect.height / 2);
    let deg = (Math.atan2(y, x) * 180) / Math.PI;
    if (deg < 0) deg += 360;
    let rel = (deg - DIAL.start + 360) % 360;
    if (rel > DIAL.sweep) rel = rel > DIAL.sweep + (360 - DIAL.sweep) / 2 ? 0 : DIAL.sweep;
    const raw = m.min + (rel / DIAL.sweep) * (m.max - m.min);
    this._pending.temp = Math.max(m.min, Math.min(m.max, Number((Math.round(raw / m.step) * m.step).toFixed(2))));
    this._update();
  }

  _bumpNumber(key, dir) {
    const m = this._numberMeta(key);
    if (!m.state) return;
    clearTimeout(this._timers[`${key}-clear`]);
    const base = this._pending[key] ?? this._num(m.state) ?? m.min;
    this._pending[key] = this._clampNumber(key, base + dir * m.step);
    this._update();
    this._debounce(key, () => this._commit(key, 0), 600);
  }

  /** Gemerkten Wert an Home Assistant schicken. */
  _commit(key, delay = 0) {
    clearTimeout(this._timers[key]);
    clearTimeout(this._timers[`${key}-clear`]);
    const value = this._pending[key];
    if (value === undefined) return;
    const send = () => {
      if (key === "temp") {
        this._hass.callService("climate", "set_temperature", {
          entity_id: this._config.entity,
          temperature: value,
        });
      } else {
        const m = this._numberMeta(key);
        if (m.id) this._hass.callService("number", "set_value", { entity_id: m.id, value });
      }
      this._timers[`${key}-clear`] = setTimeout(() => {
        delete this._pending[key];
        this._update();
      }, 3000);
    };
    delay ? setTimeout(send, delay) : send();
  }

  // ------------------------------------------------------------------------ Anzeige
  _update() {
    const $ = this.$;
    const hass = this._hass;
    const t = this._t();
    const climate = hass.states[this._config.entity];
    const card = $("card");

    if (!climate) {
      $("title").textContent = this._config.entity;
      $("notice").hidden = false;
      $("notice").textContent = `${this._config.entity}: ${t.unavailable}`;
      $("wrap").classList.add("unavail");
      return;
    }
    $("notice").hidden = true;
    const ca = climate.attributes;
    const unavailable = climate.state === "unavailable";
    $("wrap").classList.toggle("unavail", unavailable);

    // Farbe nach Betriebsart
    card.style.setProperty("--mode-color", HZ_MODE_COLORS[climate.state] || HZ_MODE_COLORS.off);

    $("title").textContent = this._config.name || ca.friendly_name || this._config.entity;

    // --- Solltemperatur
    const m = this._tempMeta(climate);
    const target = this._pending.temp ?? (ca.temperature != null ? Number(ca.temperature) : null);
    const digits = m.step < 1 ? 1 : 0;
    const unit = (hass.config && hass.config.unit_system && hass.config.unit_system.temperature) || "°C";
    if (target != null && Number.isFinite(target)) {
      const text = this._fmt(target, digits);
      const sep = text.search(/[.,]/);
      $("t-int").textContent = sep === -1 ? text : text.slice(0, sep);
      $("t-dec").textContent = sep === -1 ? "" : text.slice(sep);
      $("t-unit").textContent = unit;
      const ang = this._angleFor(target, m.min, m.max);
      $("fill").setAttribute("d", this._arc(DIAL.start, ang));
      const r = (ang * Math.PI) / 180;
      $("knob").setAttribute("cx", (DIAL.cx + DIAL.r * Math.cos(r)).toFixed(2));
      $("knob").setAttribute("cy", (DIAL.cy + DIAL.r * Math.sin(r)).toFixed(2));
      $("knob").style.display = "";
    } else {
      $("t-int").textContent = "–";
      $("t-dec").textContent = "";
      $("t-unit").textContent = "";
      $("fill").setAttribute("d", "");
      $("knob").style.display = "none";
    }

    const ctrl = this._ctrl();
    const cAttr = (ctrl && ctrl.attributes) || {};
    let cur = this._num(hass.states[cAttr.temperature_entity]);
    if (cur == null && ca.current_temperature != null && Number.isFinite(Number(ca.current_temperature))) {
      cur = Number(ca.current_temperature);
    }
    const realState = cAttr.room_temperature_entity && hass.states[cAttr.room_temperature_entity];
    const real = this._num(realState);
    $("real").textContent = cAttr.room_temperature_entity
      ? `${t.real} ${real == null ? "–" : this._fmt(real, 1) + " " + unit}`
      : "";
    const outState = cAttr.outdoor_temperature_entity && hass.states[cAttr.outdoor_temperature_entity];
    let outdoor = null;
    if (outState) {
      outdoor = outState.entity_id.startsWith("weather.")
        ? (Number.isFinite(Number(outState.attributes.temperature)) ? Number(outState.attributes.temperature) : null)
        : this._num(outState);
    }
    const outEl = $("outdoor");
    outEl.hidden = !cAttr.outdoor_temperature_entity;
    outEl.textContent = "";
    if (!outEl.hidden) {
      outEl.append(document.createTextNode(t.outdoor));
      const ob = document.createElement("b");
      ob.textContent = outdoor == null ? "–" : `${this._fmt(outdoor, 1)} ${unit}`;
      outEl.appendChild(ob);
    }
    if (cur != null && Number.isFinite(cur)) {
      $("current").textContent = `${t.simulated} ${this._fmt(cur, 1)} ${unit}`;
      const ang = this._angleFor(cur, m.min, m.max);
      const r = (ang * Math.PI) / 180;
      const r0 = DIAL.r - 14, r1 = DIAL.r + 14;
      const mark = $("curmark");
      mark.setAttribute("x1", (DIAL.cx + r0 * Math.cos(r)).toFixed(2));
      mark.setAttribute("y1", (DIAL.cy + r0 * Math.sin(r)).toFixed(2));
      mark.setAttribute("x2", (DIAL.cx + r1 * Math.cos(r)).toFixed(2));
      mark.setAttribute("y2", (DIAL.cy + r1 * Math.sin(r)).toFixed(2));
      mark.style.display = "";
    } else {
      $("current").textContent = "";
      $("curmark").style.display = "none";
    }

    $("action").textContent = unavailable
      ? t.unavailable
      : (ca.hvac_action && t.actions[ca.hvac_action]) || t.modes[climate.state] || climate.state;

    // --- Hz-Bereich
    this._updateHz(climate, t);

    // --- Betriebsarten
    this._updateModes(climate, t);

    // --- weitere Innengeräte
    this._updateUnits(t);

    $("l-comp").textContent = t.compressor;
    $("l-target").textContent = t.target_hz;
    $("l-ctrl").textContent = t.controller;
    $("l-units").textContent = t.other_units;
    $("more").setAttribute("aria-label", t.more);
  }

  _updateHz(climate, t) {
    const $ = this.$;
    const hass = this._hass;
    const ctrl = this._ctrl();
    const hzSection = $("hz-section");
    const regler = $("regler");

    if (!ctrl) {
      hzSection.hidden = true;
      regler.hidden = true;
      $("notice").hidden = false;
      $("notice").textContent = t.not_found;
      return;
    }
    hzSection.hidden = false;
    regler.hidden = false;
    const ca = ctrl.attributes;

    // Ist-Frequenz
    const hzNow = this._num(hass.states[ca.frequency_entity]);
    $("hz-val").textContent = hzNow == null ? "–" : this._fmt(hzNow, hzNow % 1 ? 1 : 0);

    // Ziel-Hz
    const tg = this._numberMeta("hz");
    const tgVal = this._pending.hz ?? this._num(tg.state);
    const input = $("hz-in");
    input.min = tg.min;
    input.max = tg.max;
    input.step = tg.step;
    if (this.shadowRoot.activeElement !== input) input.value = tgVal == null ? "" : String(tgVal);

    // Balken: Ist und Ziel (weiß)
    const scale = Math.max(50, (hzNow || 0) * 1.15, (tgVal || 0) * 1.15);
    const pct = (v) => `${Math.max(0, Math.min(100, ((v || 0) / scale) * 100))}%`;
    $("bar-fill").style.width = pct(hzNow);
    $("mark-t").style.left = pct(tgVal);

    // Regler-Schalter und Status
    const sw = hass.states[ca.switch_entity];
    const on = !!sw && sw.state === "on";
    const toggle = $("toggle");
    toggle.classList.toggle("on", on);
    toggle.setAttribute("aria-checked", on ? "true" : "false");
    const status = ctrl.state;
    const statusEl = $("status");
    statusEl.textContent = t.status[status] || status;
    statusEl.className = "status" + (status === "fault" ? " err" : status === "waiting" || status === "defrost" || status === "overheat" ? " warn" : "");

    // Details zum vorgetäuschten Sensor
    const fake = this._num(hass.states[ca.temperature_entity]);
    const off = this._num(hass.states[ca.offset_entity]);
    const fac = this._num(hass.states[ca.factor_entity]);
    const minHz = ca.learned_min_hz;
    const unit = (hass.config && hass.config.unit_system && hass.config.unit_system.temperature) || "°C";
    const parts = [];
    if (fake != null) parts.push(`${t.sensor} ${this._fmt(fake, 1)} ${unit}`);
    if (ca.passthrough && fake != null) {
      parts.push(t.passthrough);
    } else {
      if (off != null) parts.push(`${t.offset} ${off > 0 ? "+" : ""}${this._fmt(off, 2)} K`);
      if (fac != null) parts.push(`${t.factor} ${this._fmt(fac, 2)}`);
    }
    $("detail").textContent = parts.join(" · ");
    $("detail").hidden = parts.length === 0;

    // Mindest-Hz & manueller Reset-Button
    const minRow = $("min-hz-row");
    if (minRow) {
      if (minHz != null) {
        minRow.hidden = false;
        $("l-min-hz-desc").textContent = t.min_hz_label;
        $("min-hz-val").textContent = `${this._fmt(minHz, 0)} Hz`;
        $("l-reset-min").textContent = t.reset_min;
        const resetBtn = $("reset-min-hz");
        resetBtn.title = t.reset_min_title;
        resetBtn.setAttribute("aria-label", t.reset_min_title);
      } else {
        minRow.hidden = true;
      }
    }
  }

  _updateModes(climate, t) {
    const $ = this.$;
    const modes = (climate.attributes.hvac_modes || []).filter((x) => x);
    const sig = modes.join("|");
    const box = $("modes");
    if (sig !== this._modesSig) {
      this._modesSig = sig;
      box.textContent = "";
      for (const mode of modes) {
        const btn = document.createElement("button");
        btn.dataset.mode = mode;
        btn.style.setProperty("--btn-color", HZ_MODE_COLORS[mode] || HZ_MODE_COLORS.off);
        const icon = document.createElement("ha-icon");
        icon.setAttribute("icon", HZ_MODE_ICONS[mode] || "mdi:thermostat");
        btn.appendChild(icon);
        btn.addEventListener("click", () =>
          this._hass.callService("climate", "set_hvac_mode", {
            entity_id: this._config.entity,
            hvac_mode: mode,
          })
        );
        box.appendChild(btn);
      }
    }
    for (const btn of box.children) {
      const label = t.modes[btn.dataset.mode] || btn.dataset.mode;
      btn.classList.toggle("active", btn.dataset.mode === climate.state);
      btn.title = label;
      btn.setAttribute("aria-label", label);
    }
  }

  _updateUnits(t) {
    const $ = this.$;
    const ctrl = this._ctrl();
    const ids = this._config.show_units !== false && ctrl ? ctrl.attributes.indoor_units || [] : [];
    const box = $("units");
    if (!ids.length) {
      box.hidden = true;
      return;
    }
    const unit = (this._hass.config && this._hass.config.unit_system && this._hass.config.unit_system.temperature) || "°C";
    const rows = ids.map((id) => {
      const st = this._hass.states[id];
      if (!st) return [id, id, t.unavailable];
      const cur = st.attributes.current_temperature;
      const mode = st.attributes.hvac_action && t.actions[st.attributes.hvac_action]
        ? t.actions[st.attributes.hvac_action]
        : t.modes[st.state] || st.state;
      return [id, st.attributes.friendly_name || id, `${cur != null ? this._fmt(cur, 1) + " " + unit + " · " : ""}${mode}`];
    });
    const sig = JSON.stringify(rows);
    if (sig === this._unitsSig) return;
    this._unitsSig = sig;
    box.hidden = false;
    const chips = $("chips");
    chips.textContent = "";
    for (const [id, name, text] of rows) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.title = `${name} (${id})`;
      chip.setAttribute("aria-label", `${name}: ${text}`);
      const b = document.createElement("b");
      b.textContent = name;
      chip.append(b, document.createTextNode(text));
      chip.addEventListener("click", () => this._moreInfo(id));
      chips.appendChild(chip);
    }
  }
}

// ---------------------------------------------------------------------------- Editor
class AcPidFrequencyCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  _render() {
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (ev) => {
        this._config = ev.detail.value;
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config: this._config },
            bubbles: true,
            composed: true,
          })
        );
      });
      this.appendChild(this._form);
    }
    const lang = ((this._hass && this._hass.language) || "en").slice(0, 2);
    const t = HZ_I18N[lang] || HZ_I18N.en;
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { domain: "climate" } } },
      { name: "name", selector: { text: {} } },
      { name: "controller", selector: { entity: { domain: "sensor", integration: "ac_pid_frequency" } } },
      { name: "show_units", selector: { boolean: {} } },
    ];
    this._form.computeLabel = (schema) =>
      ({
        entity: t.entity,
        name: t.name,
        controller: t.controller_entity,
        show_units: t.other_units,
      }[schema.name] || schema.name);
  }
}

// Registrierung erst, wenn das HA-Frontend vollständig läuft (hass gesetzt). Vorher definierte
// Elemente können für das (gepatchte) Element-Register von HA unsichtbar bleiben
// ("Custom element doesn't exist") – je nach Ladereihenfolge mal ja, mal nein.
const HZ_DEFINE = () => {
  if (customElements.get("ac-pid-frequency-card")) return true;
  try {
    customElements.define("ac-pid-frequency-card", AcPidFrequencyCard);
    if (!customElements.get("ac-pid-frequency-card-editor")) {
      customElements.define("ac-pid-frequency-card-editor", AcPidFrequencyCardEditor);
    }
  } catch (err) {
    console.warn("AC-PID-FREQUENCY-CARD: Registrierung fehlgeschlagen", err);
  }
  return !!customElements.get("ac-pid-frequency-card");
};
(() => {
  const started = Date.now();
  const tick = () => {
    const ha = document.querySelector("home-assistant");
    if ((ha && ha.hass) || Date.now() - started > 8000) {
      HZ_DEFINE();
      return;
    }
    setTimeout(tick, 25);
  };
  tick();
})();

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "ac-pid-frequency-card")) {
  window.customCards.push({
    type: "ac-pid-frequency-card",
    name: "AC PID Frequency",
    description:
      "Thermostat-Karte mit Kompressor-Frequenz, Ziel-Hz-Eingabe und Regler-Schalter.",
    preview: false,
  });
}

console.info(
  `%c AC-PID-FREQUENCY-CARD %c ${HZ_CARD_VERSION} `,
  "color:#fff;background:#ff8100;font-weight:700",
  "color:#ff8100;background:#fff"
);
