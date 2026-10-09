# Smart Pool für Home Assistant

Eigene Integration für die Pool-Steuerung: Wasserqualität bewerten, Dosierung berechnen,
Filterlaufzeit ermitteln und – wenn gewünscht – die Pumpe selbst steuern (Zeitplan, Solar,
Dauerbetrieb, Frostschutz) inklusive Trockenlaufschutz und Rückspül-Erinnerung.

> **Sicher installierbar:** Nach der Einrichtung steht die Betriebsart auf **Manuell**.
> In diesem Modus rechnet die Integration nur – sie schaltet **nichts**. Erst wenn du eine
> andere Betriebsart wählst, übernimmt sie die Pumpe.

## Funktionen

| Bereich | Was die Integration liefert |
|---|---|
| Wasserqualität | Gesamtstatus `ok / prüfen / kritisch`, pH-Status, Redox-Status |
| Dosierung | Chlor-Menge (g) bei zu niedrigem Redox, pH-Minus / pH-Plus (g) bezogen auf dein Poolvolumen |
| Laufzeit | Empfohlene Laufzeit (Wassertemperatur ÷ 2, mind. 1× Umwälzung, + Zuschlag bei schlechtem Redox), Soll-Laufzeit inkl. Korrektur, Laufzeit heute, Restlaufzeit |
| Pumpe | Betriebsarten Manuell, Aus, Automatik (Zeitplan), Solar, Dauerbetrieb, Winter/Frostschutz |
| Sicherheit | Trockenlaufschutz über die Pumpenleistung, Schaltschutz gegen Flattern (min. 2 min), Pumpe nicht erreichbar → keine Befehle |
| Wartung | Pumpenstunden seit Rückspülen, Rückspülen fällig (Stunden oder Tage), Button „Rückgespült“ |
| Überwachung | Messung veraltet, Frostgefahr |
| Energie | Energie & Kosten heute (aus Energiezähler der Pumpe) |
| Ereignisse | `smart_pool_event` für eigene Benachrichtigungen |

### Betriebsarten

| Betriebsart | Verhalten |
|---|---|
| **Manuell** | Keine Steuerung. Nur Berechnung und Anzeige. *(Standard)* |
| **Aus** | Pumpe bleibt aus. |
| **Automatik (Zeitplan)** | Startet ab der *Startzeit* und läuft, bis die Soll-Laufzeit erreicht ist. |
| **Solar** | Startet, wenn die Solarleistung 10 min über der Schwelle liegt (optional nur ab Mindest-Akkustand). Stoppt erst nach 10 min ohne Überschuss. Ist die Soll-Laufzeit bis zur *Nachholzeit* nicht erreicht, läuft sie mit Netzstrom weiter. |
| **Dauerbetrieb** | Pumpe läuft durchgehend (z. B. Neubefüllung, Schockchlorung, Algen). |
| **Winter / Frostschutz** | Bei Außentemperatur ≤ Frostgrenze läuft die Pumpe 15 min pro Stunde, sonst aus. |

Bei einer **Pumpenstörung** (Trockenlauf) wird die Pumpe in allen Modi außer *Manuell*
abgeschaltet und bleibt aus, bis du **„Störung quittieren“** drückst.

## Installation

### Über HACS (benutzerdefiniertes Repository)

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/passi277/HA-Smart-Pool`, Typ *Integration*.
2. „Smart Pool“ installieren, Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Smart Pool*.

### Manuell

Ordner `custom_components/smart_pool` nach `config/custom_components/` kopieren und neu starten.

## Einrichtung

**Schritt 1 – Pflicht:** Name, Poolvolumen (m³), pH-Sensor, Redox-Sensor, Wassertemperatur, Pumpen-Schalter
(`switch` oder `input_boolean`).

**Schritt 2 – optional:** Pumpenleistung, Pumpen-Energiezähler, Solarleistung, Akku-Ladestand,
Außentemperatur, Zeitpunkt der letzten Messung.

Alle Parameter (Fördermenge, Min/Max-Laufzeit, Chlorprodukt, Trockenlauf-Grenze, Rückspül-Intervalle,
Solar-Schwelle, Nachholzeit, Frostgrenze …) lassen sich später unter *Konfigurieren* ändern.

### Beispiel-Zuordnung für den Garten

| Feld | Entität |
|---|---|
| pH-Sensor | `sensor.pool_ph` |
| Redox-Sensor | `sensor.pool_orp` |
| Wassertemperatur | `sensor.pool_temperature` *(Wassersensor, **nicht** die Blink-Kamera)* |
| Pumpen-Schalter | `switch.stecker_pool_switch_0` |
| Pumpenleistung | `sensor.stecker_pool_switch_0_power` |
| Pumpen-Energiezähler | `sensor.stecker_pool_switch_0_energy` |
| Solarleistung | `sensor.solarbank_3_e2700_pro_solarleistung` |
| Letzte Messung | `sensor.pool_last_measurement` |

### Umstieg von bestehenden Automationen

Solange die Betriebsart **Manuell** ist, läuft alles parallel und ohne Konflikt. Bevor du auf
*Automatik*, *Solar*, *Dauerbetrieb* oder *Winter* umstellst, solltest du deine bisherigen
Pumpen-Automationen deaktivieren – sonst schalten zwei Logiken dieselbe Pumpe.

## Entitäten

| Entität | Beschreibung |
|---|---|
| `select.<pool>_betriebsart` | Betriebsart |
| `time.<pool>_startzeit` | Startzeit für Automatik |
| `number.<pool>_laufzeit_korrektur` | ± Stunden auf die empfohlene Laufzeit |
| `number.<pool>_strompreis` | €/kWh für die Kostenberechnung |
| `sensor.<pool>_wasserqualitat`, `…_ph_status`, `…_redox_status` | Bewertung |
| `sensor.<pool>_pumpenstatus` | Was die Steuerung gerade tut und warum |
| `sensor.<pool>_empfohlene_laufzeit`, `…_soll_laufzeit`, `…_laufzeit_heute`, `…_restlaufzeit` | Laufzeit |
| `sensor.<pool>_chlor_dosierung`, `…_ph_minus_dosierung`, `…_ph_plus_dosierung` | Dosier-Richtwerte |
| `sensor.<pool>_pumpenstunden_seit_ruckspulen`, `…_letztes_ruckspulen` | Wartung |
| `sensor.<pool>_letzte_messung`, `…_energie_heute`, `…_kosten_heute` | Info |
| `binary_sensor.<pool>_ruckspulen_fallig`, `…_messung_veraltet`, `…_pumpenstorung`, `…_frostgefahr` | Warnungen |
| `button.<pool>_ruckgespult`, `…_storung_quittieren` | Aktionen |

## Ereignisse für Benachrichtigungen

Die Integration verschickt selbst keine Nachrichten, sondern feuert `smart_pool_event` mit
`type`: `water_quality_changed`, `measurement_stale`, `backwash_due`, `backwash_done`,
`pump_fault`, `pump_started`, `pump_stopped`.

```yaml
triggers:
  - trigger: event
    event_type: smart_pool_event
    event_data:
      type: pump_fault
actions:
  - action: notify.mobile_app_pascal_s26
    data:
      title: "Pool: Pumpenstörung"
      message: "Leistung {{ trigger.event.data.power }} W – Pumpe wurde gestoppt."
```

## Hinweise zu den Berechnungen

- **Wasserbereiche:** pH ok 7,2–7,6 (kritisch < 6,8 / > 8,0); Redox ok 650–800 mV (kritisch < 400 / > 900).
- **Chlor:** 1 mg/l in 1 m³ = 1 g Aktivchlor. Menge = Volumen × Anhebung ÷ Aktivchlor-Gehalt; unter 400 mV doppelt.
- **pH:** ca. 10 g pro m³ verschieben den pH-Wert um 0,1 (Zielwert 7,4).
- Alle Mengen sind **Richtwerte** – in Teilmengen dosieren und nachmessen.
- Ein dauerhaft niedriger Redox-Wert bei klarem Wasser kann auch auf eine gealterte/unkalibrierte Sonde hinweisen.

## Entwicklung

```bash
pip install -r requirements_test.txt ruff
pytest
ruff check . && ruff format --check .
```
