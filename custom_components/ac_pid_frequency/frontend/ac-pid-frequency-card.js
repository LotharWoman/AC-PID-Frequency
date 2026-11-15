/*
 * AC PID Frequency – Lovelace-Karte
 * Home Assistant custom card for climate control and AC PID diagnostics.
 */
const HZ_CARD_VERSION = "2.4.4";
const HZ_STATUS = {
  de: {
    off: "Regler aus", idle: "Wartet (kein Heizbetrieb)", raise: "Frequenz erhöhen",
    lower: "Frequenz senken", hold: "Im Zielbereich (stabil)", min_mod: "Mindestmodulation (stabil gehalten)",
    defrost: "Abtauen aktiv (pausiert)", "after-defrost-timer": "Nach-Abtau-Stabilisierung",
    overheat: "Überhitzungsschutz aktiv", waiting: "Daten fehlen – Wert gehalten",
    fault: "Fehler – Anlage nutzt eigenen Sensor",
  },
  en: {
    off: "Controller off", idle: "Waiting (not heating)", raise: "Raising frequency",
    lower: "Lowering frequency", hold: "On target (stable)", min_mod: "Minimum modulation (stabilized)",
    defrost: "Defrost active (paused)", "after-defrost-timer": "Post-defrost stabilization",
    overheat: "Overheat protection active", waiting: "Data missing – value held",
    fault: "Fault – AC uses its own sensor",
  },
};

class AcPidFrequencyCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) throw new Error("Set 'entity' to the master climate entity.");
    this._config = config;
    this._render();
  }
  set hass(hass) { this._hass = hass; this._render(); }
  getCardSize() { return 5; }

  _controller() {
    const states = this._hass?.states || {};
    if (this._config.controller) return states[this._config.controller] || null;
    return Object.values(states).find((s) => s.entity_id.startsWith("sensor.") &&
      s.attributes.ac_pid_frequency_climate === this._config.entity) || null;
  }
  _call(domain, service, data) { this._hass.callService(domain, service, data); }
  _render() {
    if (!this._config || !this._hass) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const climate = this._hass.states[this._config.entity];
    const ctrl = this._controller();
    const a = ctrl?.attributes || {};
    const status = ctrl?.state || "unavailable";
    const lang = (this._hass.language || "en").slice(0, 2);
    const labels = HZ_STATUS[lang] || HZ_STATUS.en;
    const temp = climate?.attributes.temperature;
    const current = climate?.attributes.current_temperature;
    const hz = a.frequency_entity ? this._hass.states[a.frequency_entity]?.state : null;
    const targetState = a.target_hz_entity ? this._hass.states[a.target_hz_entity] : null;
    const switchState = a.switch_entity ? this._hass.states[a.switch_entity] : null;
    const modes = climate?.attributes.hvac_modes || [];
    const unit = this._hass.config?.unit_system?.temperature || "°C";
    const escape = (v) => String(v ?? "–").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
    }[c]));
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block} ha-card{padding:16px}.head,.row{display:flex;align-items:center;justify-content:space-between;gap:12px}
        .title{font-size:18px;font-weight:500}.reading{font-size:32px;margin:12px 0}.muted{color:var(--secondary-text-color);font-size:13px}
        .status{margin:8px 0 14px}.controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
        button,select,input{font:inherit;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:8px}
        button{cursor:pointer}.controls input{width:5em}.modes{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}
        .active{border-color:var(--primary-color);color:var(--primary-color)}
      </style>
      <ha-card>
        <div class="head"><span class="title">${escape(this._config.name || climate?.attributes.friendly_name || this._config.entity)}</span>
        <span class="muted">${escape(status)}</span></div>
        <div class="reading">${escape(temp)}${temp != null ? ` ${escape(unit)}` : ""}</div>
        <div class="muted">${lang === "de" ? "Aktuell" : "Current"}: ${escape(current)}${current != null ? ` ${escape(unit)}` : ""}</div>
        <div class="status">${escape(labels[status] || status)}</div>
        <div class="row controls">
          <button id="minus" aria-label="Decrease temperature">−</button>
          <span>${lang === "de" ? "Solltemperatur" : "Set temperature"}</span>
          <button id="plus" aria-label="Increase temperature">+</button>
          <span class="muted">${lang === "de" ? "Kompressor" : "Compressor"}: ${escape(hz)} Hz</span>
        </div>
        ${targetState ? `<div class="row controls" style="margin-top:10px"><label for="target">${lang === "de" ? "Ziel-Frequenz" : "Target frequency"}</label><input id="target" type="number" min="${escape(targetState.attributes.min)}" max="${escape(targetState.attributes.max)}" step="${escape(targetState.attributes.step)}" value="${escape(targetState.state)}"><span>Hz</span></div>` : ""}
        <div class="row controls" style="margin-top:10px"><span>${lang === "de" ? "Hz-Regelung" : "Frequency control"}</span><button id="toggle">${switchState?.state === "on" ? (lang === "de" ? "Aus" : "Turn off") : (lang === "de" ? "Ein" : "Turn on")}</button></div>
        <div class="modes">${modes.map((m) => `<button class="mode ${climate?.state === m ? "active" : ""}" data-mode="${escape(m)}">${escape(m)}</button>`).join("")}</div>
      </ha-card>`;
    this.shadowRoot.getElementById("minus")?.addEventListener("click", () => this._setTemp(-1));
    this.shadowRoot.getElementById("plus")?.addEventListener("click", () => this._setTemp(1));
    this.shadowRoot.getElementById("toggle")?.addEventListener("click", () => {
      if (a.switch_entity) this._call("switch", switchState?.state === "on" ? "turn_off" : "turn_on", { entity_id: a.switch_entity });
    });
    this.shadowRoot.getElementById("target")?.addEventListener("change", (e) => {
      this._call("number", "set_value", { entity_id: a.target_hz_entity, value: Number(e.target.value) });
    });
    this.shadowRoot.querySelectorAll(".mode").forEach((button) => button.addEventListener("click", () =>
      this._call("climate", "set_hvac_mode", { entity_id: this._config.entity, hvac_mode: button.dataset.mode })
    ));
  }
  _setTemp(delta) {
    const climate = this._hass.states[this._config.entity];
    if (!climate) return;
    const step = Number(climate.attributes.target_temp_step) || 0.5;
    const min = Number(climate.attributes.min_temp) || 16;
    const max = Number(climate.attributes.max_temp) || 30;
    const next = Math.max(min, Math.min(max, Number(climate.attributes.temperature) + delta * step));
    this._call("climate", "set_temperature", { entity_id: this._config.entity, temperature: next });
  }
}
if (!customElements.get("ac-pid-frequency-card")) customElements.define("ac-pid-frequency-card", AcPidFrequencyCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "ac-pid-frequency-card")) {
  window.customCards.push({ type: "ac-pid-frequency-card", name: "AC PID Frequency", description: "Climate controls and AC PID status." });
}
console.info(`AC PID Frequency card ${HZ_CARD_VERSION}`);
