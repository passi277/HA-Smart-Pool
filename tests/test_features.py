"""Unit tests for chemistry, programs, season and stats helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from custom_components.smart_pool.chemistry import (
    Chemistry,
    low_stock_thresholds,
    product_name,
    shock_dose,
)
from custom_components.smart_pool.programs import ProgramState
from custom_components.smart_pool.season import Season, checklist
from custom_components.smart_pool.stats import (
    EnergyCounter,
    WeekStats,
    build_report,
    parse_visual,
    report_due,
    solar_savings_rate,
    swim_label,
    swim_score,
)

TZ = timezone(timedelta(hours=2))
NOW = datetime(2026, 7, 1, 12, 0, tzinfo=TZ)


def test_dose_log_consumption_and_stock():
    chem = Chemistry()
    chem.set_stock("chlorine", 200)
    chem.add_dose(NOW, "chlorine", 70, orp=535)
    chem.add_dose(NOW, "ph_minus", 100, orp=None)
    assert chem.consumption == {"chlorine": 70, "ph_minus": 100}
    assert chem.stock == {"chlorine": 130}  # pH minus not tracked
    assert chem.last_dose().product == "ph_minus"
    assert chem.last_dose("chlorine").amount == 70
    assert chem.doses_since(NOW - timedelta(hours=1)) == {"chlorine": 70, "ph_minus": 100}
    restored = Chemistry.from_dict(chem.as_dict())
    assert restored.stock == chem.stock
    assert restored.pending_check.orp_before == 535
    chem.reset_season()
    assert chem.consumption == {}


def test_low_stock_and_shopping():
    thresholds = low_stock_thresholds(volume_m3=17.2, chlorine_strength=56, metal_ex_pool_ml=520)
    assert thresholds["chlorine"] == 92
    assert thresholds["shock"] == shock_dose(17.2, 56) == 310
    assert thresholds["metal_ex"] == 520
    chem = Chemistry()
    chem.set_stock("chlorine", 50)
    chem.set_stock("metal_ex", 1000)
    assert chem.low_products(thresholds) == ["chlorine"]
    assert chem.products_to_shop(thresholds) == ["chlorine"]
    assert chem.products_to_shop(thresholds) == []  # only once
    chem.set_stock("chlorine", 1000)
    assert chem.products_to_shop(thresholds) == []
    chem.set_stock("chlorine", 10)
    assert chem.products_to_shop(thresholds) == ["chlorine"]  # re-armed after restock


def test_probe_check():
    chem = Chemistry()
    chem.add_dose(NOW, "chlorine", 30, orp=530)
    # Too early, or no new measurement yet.
    assert chem.evaluate_probe(NOW + timedelta(hours=2), 600, NOW + timedelta(hours=2)) is None
    assert chem.evaluate_probe(NOW + timedelta(hours=7), 540, NOW) is None
    result = chem.evaluate_probe(NOW + timedelta(hours=7), 540, NOW + timedelta(hours=6))
    assert (round(result.rise_mv), result.ok) == (10, False)
    assert not chem.probe_suspect
    chem.add_dose(NOW + timedelta(days=1), "shock", 300, orp=530)
    later = NOW + timedelta(days=1, hours=8)
    chem.evaluate_probe(later, 545, later)
    assert chem.probe_suspect
    chem.probe_calibrated()
    assert not chem.probe_suspect
    chem.add_dose(NOW, "chlorine", 30, orp=530)
    ok = chem.evaluate_probe(NOW + timedelta(hours=8), 620, NOW + timedelta(hours=8))
    assert ok.ok and chem.probe_failures == 0
    chem.add_dose(NOW, "chlorine", 30, orp=530)
    assert chem.evaluate_probe(NOW + timedelta(hours=60), 620, NOW + timedelta(hours=60)) is None
    assert chem.pending_check is None
    assert product_name("metal_ex", "de") == "Metall-Ex"


def test_programs():
    program = ProgramState()
    assert not program.active
    program.start("boost", NOW, 2)
    assert program.active and program.remaining_hours(NOW + timedelta(hours=1)) == 1
    assert program.tick(NOW + timedelta(hours=1)) is None
    assert program.tick(NOW + timedelta(hours=2)) == "boost"
    assert not program.active
    program.start("algae", NOW, 72)
    restored = ProgramState.from_dict(program.as_dict())
    assert restored.name == "algae" and restored.until == NOW + timedelta(hours=72)
    program.start("none", NOW, 5)
    assert not program.active


def _season_with(temps: list[float], today: date) -> Season:
    season = Season()
    for offset, temp in enumerate(reversed(temps), start=1):
        season.add_temperature(today - timedelta(days=offset), temp)
    return season


def test_season_status():
    october = date(2026, 10, 9)
    assert _season_with([11, 10, 11, 9, 10], october).status(october, False) == "winterize"
    assert _season_with([11, 10, 13, 9, 10], october).status(october, False) == "swim"
    assert _season_with([11, 10], october).status(october, False) == "swim"  # not enough data
    july = date(2026, 7, 9)
    assert _season_with([11, 10, 11, 9, 10], july).status(july, False) == "swim"
    may = date(2026, 5, 9)
    assert _season_with([13, 14, 15], may).status(may, True) == "season_start"
    assert _season_with([13, 10, 15], may).status(may, True) == "winter"
    assert checklist("winterize", "de")[0].startswith("Einwintern")


def test_maintenance():
    season = Season()
    start = date(2026, 1, 1)
    season.ensure_started(start)
    intervals = {"sand": 730, "probe": 90, "seals": 365}
    assert season.due_tasks(start + timedelta(days=89), intervals) == []
    assert season.due_tasks(start + timedelta(days=90), intervals) == ["probe"]
    season.done("probe", start + timedelta(days=90))
    assert season.next_due("probe", intervals) == start + timedelta(days=180)
    assert season.due_tasks(start + timedelta(days=400), intervals) == ["probe", "seals"]


def test_energy_and_solar():
    counter = EnergyCounter()
    counter.add(3600, 500, 300)
    counter.add(3600, 500, None)
    counter.add(3600, None, 300)
    assert round(counter.energy_kwh, 3) == 1.0
    assert round(counter.solar_kwh, 3) == 0.3
    assert counter.solar_share == 30
    assert solar_savings_rate(470, 800, 0.3) == 0.141
    assert solar_savings_rate(470, 0, 0.3) == 0


def test_weekly_report():
    sunday = datetime(2026, 10, 11, 19, 5, tzinfo=TZ)
    assert report_due(sunday, None)
    assert not report_due(sunday, sunday.date())
    assert not report_due(sunday.replace(hour=18), None)
    week = WeekStats(start=date(2026, 10, 5), runtime_s=52 * 3600)
    week.energy.add(3600 * 50, 480, 240)
    for ph in (7.1, 7.3):
        week.ph.add(ph)
    for orp in (520, 560):
        week.orp.add(orp)
    text, details = build_report(
        week, doses={"chlorine": 120}, price=0.3, language="de", now=sunday
    )
    assert text == (
        "KW 41 · 52,0 h Filter · 24,0 kWh (7,20 €) · 50 % Solar · pH 7,1–7,3 · "
        "Redox 520–560 mV · Chlor-Granulat 120 g"
    )
    assert details["solar_savings"] == 3.6
    assert WeekStats.from_dict(week.as_dict()).ph.high == 7.3


def test_swim_score():
    best = swim_score(water_temp=28, air_temp=30, rain_mm=0, thunder=False, quality="ok")
    assert best == 100 and swim_label(best) == "great"
    assert swim_score(water_temp=28, air_temp=30, rain_mm=0, thunder=False, quality="check") == 70
    cold = swim_score(water_temp=15, air_temp=12, rain_mm=6, thunder=True, quality="ok")
    assert cold == 0 and swim_label(cold) == "poor"
    assert swim_score(water_temp=None, air_temp=30, rain_mm=0, thunder=False, quality="ok") is None


def test_parse_visual():
    assert parse_visual("09.10. 12:30 · Wasser klar · sauber · offen") == []
    assert parse_visual("Wasser leicht trüb, etwas Laub") == ["cloudy", "dirty"]
    assert parse_visual("Wasser nicht trüb, keine Algen") == []
    assert parse_visual("bräunliche Verfärbung, grünlicher Rand") == ["green", "brown"]
    assert parse_visual("Water is green") == ["green"]
    assert parse_visual(None) == []


def test_multitab_helpers():
    from custom_components.smart_pool.chemistry import multitab_next, multitab_tabs

    assert multitab_tabs(17.2, 20) == 1
    assert multitab_tabs(40, 20) == 2
    assert multitab_tabs(41, 20) == 3
    assert multitab_tabs(10, 0) == 1
    assert multitab_next(None, 7) is None
    assert multitab_next(NOW, 7) == NOW + timedelta(days=7)
    assert multitab_next(NOW, 0) is None
    chem = Chemistry()
    chem.set_stock("multitab", 3)
    chem.add_dose(NOW, "multitab", 1, orp=500)
    assert chem.stock["multitab"] == 2
    assert chem.pending_check is None  # slow-dissolving tabs are not probe-checked
