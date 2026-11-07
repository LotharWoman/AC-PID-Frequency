<p align="center">
  <img src="assets/banner.png" alt="AC PID Frequency" width="720">
</p>

# AC PID Frequency

Home-Assistant-Integration (HACS), die einer Klimaanlage einen **vorgetäuschten externen Raumtemperatursensor** liefert und sie damit auf eine **Ziel-Frequenz (Hz)** des Kompressors einpendelt. Die eigentliche Regelung bleibt bei der Anlage – die Integration verschiebt nur deren Eingangsgröße in 0,1-K-Schritten.

Funktioniert mit jeder Anlage, deren Integration einen externen Raumsensor (Home-Assistant-Entität) akzeptiert **und** die Kompressor-Frequenz als Zahlen-Entität liefert. Bei Multisplit wird nur das Master-Innengerät (das zuerst eingeschaltete) angegeben. Erst mal nur **Heizbetrieb**.

## Highlights des intelligenten, selbstlernenden Algorithmus

* **Dynamisches 4-Säulen-System für Mindestmodulation & Abschaltschutz:**
  Liegt die Soll-Hz unterhalb der erreichbaren Mindestmodulation (oder schaltet die Anlage ab), fängt der Regler die Anlage sofort über einen gezielten Kälte-Offset ab und hält sie stabil auf dem Minimum. Weil die physikalische Mindestmodulation je nach Wetter und Sollwert variiert, prüft der Regler die Gültigkeit dynamisch über 4 Säulen:
  1. **Wetterzonen-Trennung:** Erlernte Min-Hz werden getrennt nach Außentemperaturzonen (Frost, Übergang, Mild) gespeichert.
  2. **User-Trigger:** Ändert der Nutzer Soll-Hz oder Solltemperatur, wird das gelernte Minimum verworfen – die Anlage darf wieder testen und neu lernen.
  3. **Wetter-Delta-Trigger (Standard: $\ge 5\,\text{K}$):** Ändert sich die Außentemperatur spürbar, wird die Mindestmodulation automatisch zur Re-Validierung freigegeben (in Optionen anpassbar).
  4. **Soft Probing (Standard: 240 min):** Läuft die Anlage über längere Zeit stabil auf Mindestmodulation, tastet sich der Regler behutsam 1 Hz tiefer vor, um ungenutztes Modulationspotenzial zu heben (in Optionen anpassbar).
* **Selbstlernende Reaktionszeit & Verstärkung:** Ermittelt dynamisch aus echten Sprungantworten der Anlage die Totzeit und den Hz-Sprung je 0,1 K. Ein manuelles Einstellen von Reaktionszeiten oder Regelverstärkungen entfällt.
* **Momentum-Erkennung (Trend-Entkopplung):** Bewegt sich der Kompressor bereits dynamisch auf das Ziel zu, wartet der Regler geduldig ab und verhindert überhastetes Nachlegen.
* **Vollständige Abtau- & Post-Defrost-Behandlung:** Erkennt Abtauzyklen (über `hvac_action` oder Sensor), friert den Zustand ein und wartet nach Ende des Abtauens eine 120-sekündige Stabilisierungsphase ab, bevor geregelt wird.
* **Wetterabhängiges 2D-Arbeitspunkt-Lernen:** Lernt den nötigen Grund-Offset getrennt nach Außentemperaturzonen (Frost `< 2 °C`, Übergang `2–10 °C`, Mild `> 10 °C`) und Frequenzbereichen.
* **Thermischer Überhitzungsschutz:** Drosselt die Frequenz sanft, wenn die tatsächliche Raumtemperatur die Solltemperatur um mehr als z. B. 1,0 K überschreitet.
* **Echte Raumtemperatur durchreichen:** Ist der Regler aus (oder die Anlage heizt nicht), gibt der erzeugte Sensor die echte Raumtemperatur 1:1 weiter – die Anlage rechnet dann weiter mit deinem Raumthermometer statt mit ihrem oft zu warmen Deckensensor.
* **Minimale Konfiguration:** Keine Notbremse oder Dutzende verwirrende Parameter mehr – das Feintuning übernimmt der Algorithmus selbst! In den Optionen sind nur noch die Sicherheitsgrenzen sowie Wettertrigger ($\ge 5\,\text{K}$) und Soft-Probing-Intervall (240 min) konfigurierbar.

## Installation

1. HACS → Benutzerdefinierte Repositories → dieses Repository als *Integration* hinzufügen → installieren → **Home Assistant neu starten**.
   (Manuell: Ordner `custom_components/ac_pid_frequency` nach `/config/custom_components/` kopieren und neu starten.)
2. Einstellungen → Geräte & Dienste → Integration hinzufügen → **AC PID Frequency**.
3. Auswählen:
   * **Master-Klimaanlage** (Pflicht)
   * **Kompressor-Frequenz** (Pflicht)
   * **Außentemperatur** (optional: Sensor oder Wetter-Entität)
   * **Echter Raumtemperatursensor** (optional: Überhitzungsschutz und Durchreichen bei ausgeschalteter Regelung)
   * **Abtau-Sensor** (optional: Binary Sensor oder Sensor)
   * **Weitere Innengeräte** (optional: nur Anzeige)
4. In der Integration der Klimaanlage den erzeugten Sensor **„Simulierte Raumtemperatur“** als externen Raumsensor eintragen.
5. Karte hinzufügen (siehe unten), **Hz-Regelung** einschalten (ist nach der Einrichtung bewusst aus).

Alles lässt sich später ändern: Integration → *Konfigurieren* → „Entitäten ändern“ bzw. „Regelparameter ändern“.

## Entitäten

| Entität | Zweck |
|---|---|
| `sensor` Simulierte Raumtemperatur | Wert für die Anlage (0,1 K). Regler aus oder Anlage heizt nicht: **echte Raumtemperatur wird durchgereicht** (Offset 0,0 K, Änderungen sofort). **Wird `unavailable`**, wenn dann der Raumsensor fehlt bzw. keiner konfiguriert ist oder wenn bei laufender Regelung Daten zu lange fehlen → die Anlage nutzt ihren eigenen Innensensor |
| `number` Ziel-Frequenz | Gewünschte Kompressor-Hz. Eingabe ist auf die erlernte Mindestmodulation nach unten begrenzt. Hier schreiben eigene Automationen hinein (z. B. PV-Logik) |
| `switch` Hz-Regelung | Regler ein/aus |
| `button` Mindest-Hz zurücksetzen | Setzt nur die erlernte Mindestmodulation der Außentemperaturzonen auf die Basiswerte zurück (z. B. zum manuellen Neu-Testen) |
| `button` Gelernte Werte zurücksetzen | Setzt alle Lerntabellen (Arbeitspunkt-Offsets, Mindestmodulation, Reaktionszeit) vollständig auf Werkseinstellungen zurück |
| Diagnose-Sensoren | Status (inkl. `defrost`, `overheat` und `min_mod`), Offset, gelernter Offset, Frequenzabweichung, erlernte Mindestmodulation |

Beispiel für eine eigene Automation (z. B. PV-Logik):

```yaml
action: number.set_value
target:
  entity_id: number.ac_pid_frequency_ziel_frequenz
data:
  value: "{{ 48 if is_state('input_boolean.pv_ueberschuss', 'on') else 22 }}"
```

## Durchreichen der echten Raumtemperatur

| Situation | Sensor „Simulierte Raumtemperatur“ |
|---|---|
| Regler **ein**, Anlage heizt | Regelwert (Soll − Offset) |
| Regler **aus** *oder* Anlage nicht im Heizbetrieb, Raumsensor liefert Wert | echte Raumtemperatur, auf 0,1 K gerundet; folgt jeder Änderung **sofort** |
| Regler aus / kein Heizbetrieb, Raumsensor fehlt oder nicht konfiguriert | `unavailable` → Anlage nutzt ihren eigenen Sensor |
| Regler ein, aber Soll-Temperatur/Hz fehlen > Fehler-Wartezeit | `unavailable` (Status `fault`) |

Die Diagnose-Attribute des Status-Sensors zeigen mit `passthrough: true`, wann durchgereicht wird; die Karte blendet das ebenfalls ein.

## Lovelace-Karte

Wird von der Integration mitgeliefert und automatisch geladen (kein Eintrag unter *Ressourcen* nötig). Im Dashboard „Karte hinzufügen“ → **AC PID Frequency**, oder per YAML:

```yaml
type: custom:ac-pid-frequency-card
entity: climate.mein_master_innengeraet
# name: Flur            (optional)
# show_units: false     (weitere Innengeräte ausblenden)
# controller: sensor.…_status   (nur falls die automatische Zuordnung scheitert)
```

Die Karte sieht aus wie die Thermostat-Karte (Ziehbogen, +/-, Betriebsarten) und zeigt zusätzlich Kompressor-Ist-Hz mit Balken (Ziel = weiß), Eingabefeld mit +/- für die Ziel-Hz (nach unten automatisch auf die erlernte Mindest-Hz begrenzt), Regler-Schalter mit Status (inkl. Abtau-, Mindestmodulations- und Überhitzungsanzeige), Anzeige der erlernten Mindest-Hz mit manuellem Reset-Button sowie weitere Innengeräte. Ein Klick auf ein weiteres Innengerät öffnet dessen Klima-Dialog (Temperatur, Lüfter usw.).

## Logo / Branding

Die Logos liegen im Ordner `custom_components/ac_pid_frequency/brand/` (`icon`, `logo`, jeweils `dark_` und `@2x`). Ab **Home Assistant 2026.3** werden sie von dort automatisch genutzt – ohne Eintrag im brands-Repository. Im Repository-Root liegen `icon.png` und `logo.png` für HACS/GitHub, unter `assets/` das Banner (`banner.png`, auch als `social-preview.png` für die GitHub-Repo-Einstellungen) und die SVG-Quellen.

## Entwicklung / Tests

```bash
pip install pytest-homeassistant-custom-component home-assistant-frontend
python -m pytest
```

## Beispiel: Markdown-Karte mit Statusübersicht

`examples/markdown-card.yaml` zeigt Frequenz, Temperaturen, Sendetemperatur, Phase und gelernten Erfahrungswert als Tabellen. Nur die Entität des Status-Sensors in der ersten Template-Zeile muss angepasst werden, alles andere liest das Template aus dessen Attributen.
