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
| Metall-Ex | Nachfüllen per Knopf erfassen, Metall-Ex-Menge in ml, richtige Reihenfolge (pH → Metall-Ex → Chlor), Pumpe läuft während der Behandlung durch, danach Rückspül-Erinnerung |
| Wetter & Regen | Regen letzte 24 h (Regenmesser oder aus Vorhersage geschätzt), Regen-Vorhersage in mm und Litern, Starkregen, Hitze/UV, Gewitter → Wetter-Hinweis und automatische Extra-Laufzeit |
| Energie | Energie & Kosten heute (aus Energiezähler der Pumpe) |
| Chemie-Tagebuch | Zugaben erfassen (Knopf oder Dienst), Verbrauch pro Saison, **Sonden-Check**: steigt Redox nach dem Chloren nicht, kommt „Sonde prüfen“ |
| Vorräte | Lagerbestand je Pflegemittel, sinkt mit jeder Zugabe; knapp → automatisch auf die Einkaufsliste |
| Sonderprogramme | Boost, Schockchlorung, Neubefüllung, Algen – jeweils mit automatischem Ende und Folge-Hinweis |
| Kamera & Sicherheit | KI-/Kamera-Befund (trüb, grün, braun, Schmutz) fließt in den Handlungshinweis; Bewegung am Pool bei Abwesenheit |
| Saison & Wartung | Einwintern/Saisonstart nach Wassertemperatur, Wartungs-Erinnerungen (Sand, Sonde, Dichtungen), eigene **Aufgabenliste** mit Checklisten |
| Verbindungswächter | Pumpen-Ausfälle pro Tag, Warnung und Eintrag unter *Reparaturen* bei instabiler Verbindung |
| Statistik | Solarstrom und Solar-Ersparnis der Pumpe, Wochenbericht (Sonntag 19 Uhr), Badewetter 0–100 |
| Ereignisse & Dienste | `smart_pool_event` für eigene Benachrichtigungen, Dienste `smart_pool.log_dose` und `smart_pool.start_program`, Diagnose-Download |

### Betriebsarten

| Betriebsart | Verhalten |
|---|---|
| **Manuell** | Keine Steuerung. Nur Berechnung und Anzeige. *(Standard)* |
| **Aus** | Pumpe bleibt aus. |
| **Automatik (Zeitplan)** | Startet ab der *Startzeit* und läuft, bis die Soll-Laufzeit erreicht ist. |
| **Solar** | Startet, wenn die Solarleistung 10 min über der Schwelle liegt (optional nur ab Mindest-Akkustand). Stoppt erst nach 10 min ohne Überschuss. Ist die Soll-Laufzeit bis zur *Nachholzeit* nicht erreicht, läuft sie mit Netzstrom weiter. |
| **Dauerbetrieb** | Pumpe läuft durchgehend (z. B. Neubefüllung, Schockchlorung, Algen). |

Während einer **Metall-Ex-Behandlung** läuft die Pumpe in *Automatik*, *Solar* und *Winter* durch –
unabhängig von der Tageslaufzeit. *Manuell* und *Aus* bleiben unangetastet.
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
Außentemperatur, Zeitpunkt der letzten Messung, Wettervorhersage (`weather.*`), Regenmesser,
WLAN-Signal des Pumpen-Steckers, Kamera-/KI-Befund, Bewegungsmelder, Anwesenheit, Einkaufsliste.

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
| Wettervorhersage | `weather.pirateweather` |
| Kamera-/KI-Befund | `input_text.pool_ki_befund` |
| Bewegung am Pool | `binary_sensor.pool_bewegung` |
| Anwesenheit | `input_boolean.anwesend` |
| Einkaufsliste | `todo.einkaufsliste` |

### Empfohlene Einstellungen für den Garten-Pool (Intex Ultra XTR 549 × 274 × 132 cm)

| Einstellung | Wert | Begründung |
|---|---|---|
| Poolvolumen | **17,2 m³** | Herstellerangabe bei 90 % Füllung |
| Wasserfläche | **15,0 m²** | 5,49 m × 2,74 m → 1 mm Regen = 15 l, 1 cm Wasserstand = 150 l |
| Wettervorhersage | `weather.pirateweather` | liefert stündliche Vorhersage inkl. Regen und UV |
| Metall-Ex pro m³ Frischwasser | **60 ml** | Steinbach Metall-EX: 0,3–0,6 l pro 10 m³ – oberer Wert wegen eisenhaltigem Brunnenwasser |
| Metall-Ex pro m³ Becken | **30 ml** | vorbeugende Dosis für das ganze Becken |
| Filterlaufzeit nach Metall-Ex | **48 h** | Herstellerangabe Steinbach |
| Starkregen ab | **10 mm** in 24 h | |
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
| Metall-Ex nach 2 cm Nachfüllen (300 l) | **20 ml** |
| Metall-Ex ganzes Becken vorbeugend / bei Verfärbung | **520 ml** / **1030 ml** |

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
| `sensor.<pool>_wetter_hinweis`, `…_regen_letzte_24_h`, `…_regen_vorhersage_24_h` | Wetter & Regen |
| `sensor.<pool>_metall_ex_dosierung`, `…_metall_ex_restzeit` | Metall-Ex |
| `number.<pool>_nachfullmenge` | cm pro Nachfüllen |
| `binary_sensor.<pool>_ruckspulen_fallig`, `…_messung_veraltet`, `…_pumpenstorung`, `…_frostgefahr`, `…_starkregen`, `…_metall_ex_behandlung` | Warnungen / Zustände |
| `button.<pool>_ruckgespult`, `…_storung_quittieren`, `…_nachgefullt`, `…_metall_ex_zugegeben` | Aktionen |

## Metall-Ex bei eisenhaltigem Brunnenwasser

Eisen im Füllwasser oxidiert durch Chlor und färbt das Wasser braun/grün. Smart Pool führt
deshalb durch die richtige Reihenfolge (nach Steinbach-Anleitung):

1. **Nachgefüllt** drücken – vorher unter *Nachfüllmenge* die cm einstellen (Standard 2 cm).
   Smart Pool rechnet die Liter aus und zeigt die **Metall-Ex-Dosierung** in ml.
2. Der **Handlungshinweis** sagt, ob vorher der pH auf **7,0–7,4** gebracht werden muss, und
   empfiehlt **kein Chlor**, bis Metall-Ex im Becken ist.
3. Metall-Ex bei laufender Pumpe zugeben und **Metall-Ex zugegeben** drücken.
   Die Pumpe läuft jetzt **48 h** durch (*Metall-Ex Restzeit*), Chlor ist wieder erlaubt.
4. Danach meldet *Rückspülen fällig* – rückspülen und **Rückgespült** drücken.

Für eine Behandlung des ganzen Beckens (z. B. bei Verfärbung) einfach direkt Metall-Ex zugeben
und den Knopf drücken; die Mengen fürs ganze Becken stehen als Attribute an der
*Metall-Ex-Dosierung*. Ab nächstem Jahr kann statt des Knopfs ein Durchflussmesser angebunden werden.

## Wetter und Regen

Mit einer Wettervorhersage (`weather.*`) holt Smart Pool alle 30 Minuten die stündliche
Vorhersage (sonst die tägliche):

| | Wirkung |
|---|---|
| **Regen letzte 24 h** | vom Regenmesser (Tages- oder Gesamtzähler) oder aus der stündlichen Vorhersage geschätzt |
| **Starkregen** (≥ 10 mm) | +1 h Filterlaufzeit, Hinweis „pH und Redox prüfen“, Ereignis `heavy_rain` |
| **Regen erwartet** (≥ 2 mm) | Hinweis „Nachfüllen mit Brunnenwasser verschieben“ inkl. erwarteter Liter – Regenwasser ist eisenfrei |
| **Hitze ≥ 30 °C oder UV ≥ 7** | +1 h Filterlaufzeit, Hinweis „abends chloren“ |
| **Gewitter** | Hinweis „danach Filter länger laufen lassen“ |

Die Hinweise stehen im Sensor **Wetter-Hinweis** (`ok`, wenn nichts anliegt).

## Chemie-Tagebuch und Sonden-Check

Jede Zugabe wird erfasst – entweder über **Pflegemittel** (Auswahl) + **Zugabemenge** + **Zugabe
erfassen** (die Menge wird mit der aktuellen Empfehlung vorbelegt) oder per Dienst:

```yaml
action: smart_pool.log_dose
data:
  config_entry_id: <Smart-Pool-Eintrag>
  product: chlorine        # chlorine, shock, ph_minus, ph_plus, metal_ex
  amount: 30               # leer = empfohlene Menge
```

- **Verbrauch** je Pflegemittel für die Saison (*Neue Saison* setzt ihn zurück), **Letzte Zugabe** mit den
  letzten 10 Einträgen.
- **Sonden-Check:** Nach Chlor/Chlor-Schock prüft Smart Pool mit der nächsten Messung (frühestens nach 6 h),
  ob der Redox-Wert um mindestens 30 mV gestiegen ist. Zweimal hintereinander ohne Reaktion →
  *Sonde prüfen*, Hinweis im Handlungshinweis und Aufgabe „Sonde kalibrieren“. *Sonde kalibriert* setzt das zurück.

### Multitabs

Multitabs (z. B. ProPool Vario Tabs 7-in-1, 200 g) werden in **Tabs** erfasst. Smart Pool empfiehlt
1 Tab je angefangene 20 m³ (einstellbar) und erinnert nach 7 Tagen (einstellbar) an den nächsten Tab –
als *Multitab fällig* und im Handlungshinweis. Da Tabs langsam über Tage wirken, zählen sie nicht für den
Sonden-Check.

### Wartungsdaten rückwirkend eintragen

```yaml
action: smart_pool.set_maintenance_date
data:
  config_entry_id: <Smart-Pool-Eintrag>
  task: backwash          # backwash, sand, probe, seals
  date: "2026-09-10"
  pump_hours: 31.5        # nur Rückspülen: Pumpenstunden seitdem
```

## Vorräte und Einkaufsliste

Unter **Vorrat …** den Bestand je Pflegemittel eintragen (g bzw. ml) – nur eingetragene Mittel werden
verfolgt. Jede Zugabe zieht die Menge ab. Fällt ein Vorrat unter die Grenze, geht *Vorrat knapp* an und
das Mittel landet einmal auf der Einkaufsliste („Pool: Chlor-Granulat“).

| Pflegemittel | knapp unter |
| Multitabs | 2 Tabs |
|---|---|
| Chlor-Granulat | 3 normale Dosen (bei 17,2 m³: ca. 90 g) |
| Chlor-Schock | 1 Schock-Dosis (10 mg/l, ca. 310 g) |
| pH-Minus / pH-Plus | Menge für 0,6 pH (ca. 1 kg) |
| Metall-Ex | 1 vorbeugende Dosis fürs ganze Becken (ca. 520 ml) |

## Sonderprogramme

Über **Programm** (Auswahl) oder den Dienst `smart_pool.start_program` – die Pumpe läuft durch (außer in
*Manuell*/*Aus*), danach geht es automatisch zurück zur Betriebsart:

| Programm | Dauer | Danach |
|---|---|---|
| **Boost** | *Boost-Dauer* (Standard 2 h) | – |
| **Schockchlorung** | 24 h | Hinweis „Wasserwerte prüfen“ bis zur nächsten Messung |
| **Neubefüllung** | 48 h | ganzes Becken gilt als Frischwasser → Metall-Ex-Menge fürs ganze Becken; danach rückspülen |
| **Algen** | 72 h | rückspülen |

## Kamera und Sicherheit

- **Kamera-/KI-Befund:** Ein Text wie „Wasser leicht trüb“ wird ausgewertet (trüb, grün/Algen, braun/Eisen,
  Schmutz/Laub – Verneinungen wie „nicht trüb“ werden erkannt). Daraus entstehen Hinweise wie
  „Wasser trüb trotz guter Werte – rückspülen, Sonde prüfen“ oder „bräunlich: Metall-Ex zugeben“.
- **Bewegung bei Abwesenheit:** Bewegung am Pool, während die Anwesenheit nicht „home“/„on“ ist →
  Binärsensor und Ereignis `motion_while_away` (höchstens alle 10 min).

## Saison, Wartung und Aufgabenliste

- **Saison:** Liegt das Wasser 5 Tage im Mittel unter 12 °C (August–Dezember) → *Einwintern empfohlen*.
  In der Betriebsart *Winter* und 3 Tagen über 12 °C (März–Juni) → *Saisonstart empfohlen*.
- **Wartung:** Filtersand (alle 730 Tage), Sonde kalibrieren (90 Tage), Dichtungen prüfen (365 Tage) –
  gezählt ab Installation, erledigt per Knopf. Intervalle unter *Konfigurieren*.
- Alle Schritte landen als Checkliste in der eigenen **Aufgabenliste** (`todo.<pool>_aufgaben`), die sich wie
  jede HA-Liste abhaken und erweitern lässt.

## Verbindungswächter

Jedes Mal, wenn der Pumpen-Schalter nicht erreichbar wird, zählt *Pumpen-Ausfälle heute* hoch. Ab der
eingestellten Grenze (Standard 5) geht *Pumpen-Verbindung instabil* an und unter *Einstellungen →
Reparaturen* erscheint ein Hinweis mit dem WLAN-Signal des Steckers.

## Statistik

- **Solarstrom heute**, **Solaranteil heute**, **Solar-Ersparnis heute/aktuell** – aus Pumpen- und Solarleistung.
- **Wochenbericht:** Sonntag ab 19 Uhr, z. B. „KW 41 · 52,0 h Filter · 24,0 kWh (7,20 €) · 50 % Solar ·
  pH 7,1–7,3 · Redox 520–560 mV · Chlor-Granulat 120 g“ – als Sensor und Ereignis `weekly_report`.
- **Badewetter** 0–100 aus Wasser- und Lufttemperatur, Regen, Gewitter und Wasserqualität.
- **Diagnose:** *Geräte & Dienste → Smart Pool → Diagnose herunterladen*.

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
`pump_fault`, `pump_started`, `pump_stopped`, `heavy_rain`, `refilled`, `metal_ex_added`,
`metal_ex_done`, `dose_logged`, `probe_check`, `stock_low`, `program_started`, `program_done`,
`season`, `maintenance_due`, `connection_unstable`, `weekly_report`, `visual_finding`,
`motion_while_away`.

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
# Übersetzungen neu erzeugen:
python scripts/gen_translations.py en > custom_components/smart_pool/strings.json
cp custom_components/smart_pool/strings.json custom_components/smart_pool/translations/en.json
python scripts/gen_translations.py de > custom_components/smart_pool/translations/de.json
```
