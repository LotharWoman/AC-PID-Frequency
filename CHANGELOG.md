# Changelog

## 2.5.0 (noch nicht veröffentlicht)

Änderungen gegenüber 2.4.5. Gelernte Werte bleiben beim Update erhalten, es gibt keine neuen Optionen.

### Neu
* **Vorsteuerung bei großen Zielsprüngen:** Ändert sich die Ziel-Frequenz um mindestens 4 Hz, verschiebt der Regler den Sensorwert sofort um 60 % der aus der erlernten Verstärkung erwarteten Strecke (höchstens 1,0 K). Den Rest holt die normale Regelung in kleinen Schritten nach. Das verkürzt das Einregeln bei großen Sprüngen (im Anlagenmodell etwa um 1 bis 6 Minuten).
  * Greift nicht bei Abweichungen unter 4 Hz, bei Abtauung und Nach-Abtau-Phase, bei stehendem Kompressor, beim Erststart ohne Ausgabewert und wenn der Kompressor bereits kräftig in Zielrichtung läuft.
  * Liegt das Ziel unter der Mindestmodulation, wird nie wärmer als der sichere Halte-Offset gestellt.
  * Der Sprung wird nicht als Einzelschritt in die gelernte Verstärkung eingerechnet.
  * Stellgrößen im Code (`regelung.py`): `FF_GAIN` (0,6), `FF_MAX_K` (1,0), `FF_MIN_JUMP_HZ` (4,0).

### Geändert
* **Gelernte Mindest-Hz bei Zieländerung:** Das Minimum wird nur noch verworfen, wenn das neue Ziel *unter* dem gelernten Minimum liegt. Ein Ziel darüber (z. B. wechselnde Ziele einer PV-Logik) lässt es unberührt, die Anlage wird nicht mehr bei jedem Wechsel zum erneuten Austesten freigegeben. Eine Änderung der Solltemperatur setzt es wie bisher zurück.

### Behoben
* **Alte Schrittbeobachtung nach Pause, Aus oder Störung:** Beim Ausschalten (oder wenn die Anlage nicht heizt, oder nach Ablauf des Störungs-Timeouts) blieb die Beobachtung des letzten Schritts stehen. Nach dem Wiedereinschalten wurde dann die Frequenzänderung durch das Wiederanlaufen als Reaktion auf diesen alten Schritt gewertet und die gelernte Verstärkung falsch gelernt (Beispiel: 15 → ca. 43 Hz/K). Jetzt werden Beobachtung, Trend, Frequenzhistorie, Abtau-Merker und letzte Betriebsfrequenz zurückgesetzt (`State.reset_observation()`). Gelernte Werte und die letzte Ausgabe bleiben erhalten.

### Dokumentation
* README (de/en): Die Ziel-Frequenz-Entität nimmt 10 bis 120 Hz an, nur die Karte begrenzt nach unten; unterhalb der Mindestmodulation regelt der Regler intern auf diese.
* README (de/en): Der Überhitzungsschutz nutzt ohne echten Raumsensor `current_temperature` der Klimaanlage. Meldet sie den simulierten Wert zurück (z. B. ProtoArt), kann er eine echte Überhitzung nicht erkennen. Der Raumsensor wird außerdem für das Neustart-Halten genannt.
* README (de/en): Regeltakt (60 s) und Störungs-Timeout (10 min) sind fest voreingestellt.
* Docstring `regelung.py`: 5 statt 4 Säulen, passend zur README.

### Tests
* 14 neue Tests im Regelkern (Vorsteuerung, Mindest-Hz-Regel, Reset der Beobachtung), 1 neuer Home-Assistant-Test (Pause verwirft Schrittbeobachtung).
* Ein bestehender Test (`test_probing_and_reset_respect_configured_zone_floor`) wurde an die neue Mindest-Hz-Regel angepasst.

### Intern
* Version in `manifest.json` und in der Karte (`ac-pid-frequency-card.js`) auf 2.5.0.
