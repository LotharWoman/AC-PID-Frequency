# AC PID Frequency

Home-Assistant-Integration (HACS), die einer Klimaanlage einen **vorgetäuschten externen Raumtemperatursensor** liefert und sie damit auf eine **Ziel-Frequenz (Hz)** des Kompressors einpendelt. Die eigentliche Regelung bleibt bei der Anlage – die Integration verschiebt nur deren Eingangsgröße in 0,1-K-Schritten.

Funktioniert mit jeder Anlage, deren Integration einen externen Raumsensor (Home-Assistant-Entität) akzeptiert **und** die Kompressor-Frequenz als Zahlen-Entität liefert. Bei Multisplit wird nur das Master-Innengerät (das zuerst eingeschaltete) angegeben. Erst mal nur **Heizbetrieb**.

## Installation

1. HACS → Benutzerdefinierte Repositories → dieses Repository als *Integration* hinzufügen → installieren → Home Assistant neu starten.
   (Manuell: Ordner `custom_components/ac_pid_frequency` nach `/config/custom_components/` kopieren.)
2. Einstellungen → Geräte & Dienste → Integration hinzufügen → **AC PID Frequency**.
3. Auswählen: Master-Klimaanlage, Entität der Kompressor-Frequenz, optional weitere Innengeräte (nur Anzeige).
4. In der Integration der Klimaanlage den erzeugten Sensor **„Simulierte Raumtemperatur“** als externen Raumsensor eintragen.
5. Karte hinzufügen (siehe unten), **Hz-Regelung** einschalten (ist nach der Einrichtung bewusst aus).

Alles lässt sich später ändern: Integration → *Konfigurieren* → „Entitäten ändern“ bzw. „Regelparameter ändern“.

## Entitäten

| Entität | Zweck |
|---|---|
| `sensor` Simulierte Raumtemperatur | Wert für die Anlage (0,1 K). **Wird `unavailable`**, wenn der Regler aus ist, die Anlage nicht heizt oder Daten zu lange fehlen → die Anlage nutzt ihren eigenen Innensensor |
| `number` Ziel-Frequenz | Gewünschte Kompressor-Hz. Hier schreiben eigene Automationen hinein (z. B. PV-Logik) |
| `number` Notbremse-Frequenz | Oberhalb davon wird der Sensor sofort wärmer gestellt (Standard 70 Hz) |
| `switch` Hz-Regelung | Regler ein/aus |
| `button` Lernfaktor zurücksetzen | Lernfaktor auf 1,0 |
| Diagnose-Sensoren | Status, Offset zur Solltemperatur, Lernfaktor, Frequenzabweichung |

Beispiel für eine eigene Automation (statt integrierter PV-/Eco-Logik):

```yaml
action: number.set_value
target:
  entity_id: number.ac_pid_frequency_ziel_frequenz
data:
  value: "{{ 48 if is_state('input_boolean.pv_ueberschuss', 'on') else 22 }}"
```

## Lovelace-Karte

Wird von der Integration mitgeliefert und automatisch geladen (kein Eintrag unter *Ressourcen* nötig). Im Dashboard „Karte hinzufügen“ → **AC PID Frequency**, oder per YAML:

```yaml
type: custom:ac-pid-frequency-card
entity: climate.mein_master_innengeraet
# name: Flur            (optional)
# show_units: false     (weitere Innengeräte ausblenden)
# controller: sensor.…_status   (nur falls die automatische Zuordnung scheitert)
```

Die Karte sieht aus wie die Thermostat-Karte (Ziehbogen, +/-, Betriebsarten) und zeigt zusätzlich Kompressor-Ist-Hz mit Balken (Ziel = weiß, Notbremse = rot), Eingabefeld mit +/- für die Ziel-Hz, Regler-Schalter mit Status, Notbremse und weitere Innengeräte (nur Anzeige). Lüfter, Swing usw. erreichst du über die drei Punkte (Detaildialog der Klimaanlage).

## Regelung (1:1 aus `klima_srk35_auto.yaml` v8.1)

Fehler `err = Ziel − Ist` in Hz, Sensorwert `= Soll − Offset` (Offset > 0 → Anlage hält den Raum für kälter → mehr Hz).

| Situation | Offset | Änderungsgeschwindigkeit |
|---|---|---|
| Ist > Notbremse | −0,5 K | max. 0,08 K/min |
| err > +3 Hz (zu wenig Hz) | +0,6 K | max. 0,1 K/min |
| err < −3 Hz (zu viel Hz) | −0,4 K | sofort |
| im Totband ±3 Hz | letzter Offset, begrenzt auf ±0,3 K | max. 0,08 K/min |

Der Offset wird mit dem **Lernfaktor** (0,6 … 1,2) multipliziert: −0,1 bei erkanntem Pendeln, +0,05 je Takt im Totband, sonst Rückkehr auf mindestens 0,8. Alle Zahlen sind unter *Regelparameter ändern* einstellbar; Standardwerte = deine YAML. Zusätzlich gibt es eine Sicherheitsgrenze (Standard Soll ± 1,0 K) statt fester 16–24 °C.

Lernfaktor, letzter Sensorwert, Ziel-Hz, Notbremse und Schalterstellung überleben Neustarts.

## Unterschiede zur YAML

* PV-Überhitzung und Eco-Nachführung gibt es bewusst nicht (eigene Automation → `number` Ziel-Frequenz).
* Der Lernfaktor wird beim Verlassen des Heizbetriebs **nicht** zurückgesetzt (dafür der Knopf); nur die Frequenz-Historie wird gelöscht.
* Außerhalb des Heizbetriebs oder bei ausgeschaltetem Regler ist der Sensor `unavailable`, statt den letzten Wert stehen zu lassen.
* Die Schrittbegrenzung gilt je 60 s und wird bei anderem Regeltakt umgerechnet.

## Entwicklung / Tests

```bash
pip install pytest-homeassistant-custom-component home-assistant-frontend
python -m pytest
```

`tests/test_regelung.py` vergleicht den Regelkern über viele Zufallsfolgen mit einer direkten Abschrift der YAML-Logik.
