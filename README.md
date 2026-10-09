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
| Laufzeit | Empfohlene Laufzeit (Wassertemperatur ÷ 2, mind. 1× Umwälzung, + Zuschlag bei schlechtem Redox), Soll-Laufzeit (folgt der Empfehlung oder fest eingestellt), Laufzeit heute, Restlaufzeit |
| Hinweis | Handlungshinweis als Text, z. B. „Redox zu niedrig: ca. 70 g Chlor zugeben“ (`ok`, wenn nichts zu tun ist) |
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

### Empfohlene Einstellungen für den Garten-Pool (Intex Ultra XTR 549 × 274 × 132 cm)

| Einstellung | Wert | Begründung |
|---|---|---|
| Poolvolumen | **17,2 m³** | Herstellerangabe bei 90 % Füllung |
| Pumpen-Fördermenge | **0** (unbekannt) oder Wert vom Typenschild | Die Sandfilteranlage schafft das Volumen in ca. 3 h. Die Laufzeit-Regel Temperatur ÷ 2 liegt fast immer darüber |
| Trockenlauf-Grenze | **300 W** | Die Pumpe zieht im Betrieb ca. 470 W (gemessen am Shelly-Stecker). Bei Luft im System oder Trockenlauf fällt die Leistung deutlich ab |
| Aktivchlor-Gehalt | **56 %** (Dichlor-Granulat) bzw. dein Produkt | |
| Chlor-Anhebung pro Dosis | **1 mg/l** | |
| Rückspülen | **50 h** / spätestens **14 Tage** | wie bisher in der Garten-Integration |
| Solar-Startschwelle | **400 W** | wie im bisherigen Smart-Modus, knapp unter dem Pumpenverbrauch |
| Strompreis | **0,30 €/kWh** | |

Daraus ergibt sich für diesen Pool:

| | Wert |
|---|---|
| pH um 0,1 verschieben | ca. **170 g** pH-Minus/-Plus |
| Chlor bei Redox unter 650 mV | ca. **30 g** Dichlor-Granulat (unter 400 mV ca. 60 g) |
| Laufzeit bei 15 °C Wasser | 7,5 h (+1 h bei zu niedrigem Redox) |
| Laufzeit im Hochsommer (ab 24 °C) | 12 h (Obergrenze) |
| Stromkosten pro Laufstunde | ca. 0,47 kWh ≈ **0,14 €** |

### Umstieg von bestehenden Automationen

Solange die Betriebsart **Manuell** ist, läuft alles parallel und ohne Konflikt. Bevor du auf
*Automatik*, *Solar*, *Dauerbetrieb* oder *Winter* umstellst, solltest du deine bisherigen
Pumpen-Automationen deaktivieren – sonst schalten zwei Logiken dieselbe Pumpe.

## Entitäten

| Entität | Beschreibung |
|---|---|
| `select.<pool>_betriebsart` | Betriebsart |
| `time.<pool>_startzeit` | Startzeit für Automatik |
| `number.<pool>_soll_laufzeit` | Ziel-Laufzeit pro Tag in Stunden |
| `switch.<pool>_empfehlung_automatisch_ubernehmen` | An = Soll-Laufzeit folgt der Empfehlung; ein eigener Wert schaltet es aus, „Empfehlung übernehmen“ wieder an |
| `number.<pool>_strompreis` | €/kWh für die Kostenberechnung |
| `sensor.<pool>_wasserqualitat`, `…_ph_status`, `…_redox_status` | Bewertung |
| `sensor.<pool>_pumpenstatus` | Was die Steuerung gerade tut und warum |
| `sensor.<pool>_handlungshinweis` | Was jetzt zu tun ist |
| `sensor.<pool>_empfohlene_laufzeit`, `…_laufzeit_heute`, `…_restlaufzeit` | Laufzeit |
| `sensor.<pool>_chlor_dosierung`, `…_ph_minus_dosierung`, `…_ph_plus_dosierung` | Dosier-Richtwerte |
| `sensor.<pool>_pumpenstunden_seit_ruckspulen`, `…_letztes_ruckspulen` | Wartung |
| `sensor.<pool>_letzte_messung`, `…_energie_heute`, `…_kosten_heute` | Info |
| `binary_sensor.<pool>_ruckspulen_fallig`, `…_messung_veraltet`, `…_pumpenstorung`, `…_frostgefahr` | Warnungen |
| `button.<pool>_ruckgespult`, `…_storung_quittieren` | Aktionen |

## Modern Pool Card

Smart Pool liefert alles, was die **Modern Pool Card** (`custom:ha-pool-card` aus *Modern Cards*) braucht.
Die passende Zuordnung steht fertig im Attribut **`card_entities`** von `sensor.<pool>_wasserqualitat`
(*Entwicklerwerkzeuge → Zustände*) – einfach in die Karte übernehmen. Die Entitäts-IDs können bei
dir anders heißen (z. B. mit `_2`, wenn es schon gleichnamige Entitäten gibt).

```yaml
type: custom:ha-pool-card
pump: switch.stecker_pool_switch_0
pump_power: sensor.stecker_pool_switch_0_power
temperature: sensor.pool_temperature
ph: sensor.pool_ph
orp: sensor.pool_orp
solar_power: sensor.solarbank_3_e2700_pro_solarleistung
mode: select.pool_betriebsart
target_mode: auto                      # Modus, in dem die Soll-Laufzeit gilt
start_time: time.pool_startzeit
target_runtime: number.pool_soll_laufzeit
recommended_runtime: sensor.pool_empfohlene_laufzeit
runtime_today: sensor.pool_laufzeit_heute
guidance: sensor.pool_handlungshinweis
quality: sensor.pool_wasserqualitat
last_measurement: sensor.pool_letzte_messung
measurement_stale: binary_sensor.pool_messung_veraltet
energy_today: sensor.pool_energie_heute
cost_today: sensor.pool_kosten_heute
backwash:
  due: binary_sensor.pool_ruckspulen_fallig
  hours: sensor.pool_pumpenstunden_seit_ruckspulen   # Intervall kommt aus dem Attribut interval_hours
  last: sensor.pool_letztes_ruckspulen
  done_button: button.pool_ruckgespult
# Bereiche wie in Smart Pool:
ranges: { ph: [6.8, 7.2, 7.6, 8.0], orp: [400, 650, 800, 900] }
```

Hinweis: Die Karte zeigt die Betriebsarten mit ihren internen Namen (`manual`, `auto`, `solar` …).

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
