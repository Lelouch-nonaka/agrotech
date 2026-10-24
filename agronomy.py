# -*- coding: utf-8 -*-
"""Агрономические производные для «Агро-Радара».

Считается из данных поля (fields.json) и агрономических норм культур
(data.CROPS) — без «чёрного ящика»:

* паспорт почвы: обеспеченность N-NO3 / P2O5 / K2O против целевого для
  культуры, pH, гумус, потребность в удобрениях в кг д.в./га;
* календарь фенофаз: даты, статус (пройдена/текущая/предстоит), дни до уборки;
* индексы вегетации: NDVI / EVI / SAVI / GNDVI — модельный ряд, откалиброванный
  по измеренному NDVI поля;
* опрыскивания: план/факт, ближайшая обработка, стоимость.

Формулы и допущения — в docs/agronomy.md.
"""
from datetime import date, timedelta

from data import CROPS

MG_KG_TO_KG_HA = 3.0          # 1 мг/кг в слое 0–30 см ≈ 3 кг/га

SUPPLY_BANDS = [(0.70, "низкое"), (0.90, "ниже нормы"), (1.15, "оптимальное"),
                (1.40, "выше нормы"), (9.99, "высокое")]

FERTILIZERS = {
    "n": ("КАС-32", 0.32, 1.28, "л/га"),
    "p": ("аммофос N12P52", 0.52, 1.00, "кг/га"),
    "k": ("хлористый калий K60", 0.60, 1.00, "кг/га"),
}

NUTRIENTS = [("n", "Азот (N-NO3)", "n_mg_kg"),
             ("p", "Фосфор (P2O5)", "p_mg_kg"),
             ("k", "Калий (K2O)", "k_mg_kg")]

# ------------------------------------------------------------ индексы ------
# Спектральные «концы» смешения: открытая почва и плотная растительность.
OPTICAL = {"r_soil": 0.12, "nir_soil": 0.16, "g_soil": 0.14, "b_soil": 0.09,
           "r_veg": 0.045, "nir_veg": 0.50, "g_veg": 0.10, "b_veg": 0.035}

# Кривая проективного покрытия по ходу сезона (доля от максимума).
CANOPY_ANCHORS = [0.12, 0.35, 0.62, 0.82, 0.95, 1.00, 0.95, 0.78, 0.50]


def _band(ratio):
    for limit, title in SUPPLY_BANDS:
        if ratio < limit:
            return title
    return "высокое"


def soil_report(field):
    """Агрохимический паспорт + дозы удобрений под целевое содержание."""
    sa = field.get("soil_analysis")
    if not sa:
        return None
    crop = CROPS.get(field.get("culture_key"), {})
    target = crop.get("soil_target", {"n": 18, "p": 180, "k": 220})
    removal = crop.get("removal_kg_t", {"n": 30, "p": 12, "k": 26})
    yield_pot = field.get("yield_potential", 4.0)

    nutrients, deficits = [], {}
    for key, title, src in NUTRIENTS:
        value = float(sa.get(src, 0.0))
        goal = float(target.get(key, 0.0))
        ratio = value / goal if goal else 1.0
        need = max(0.0, (goal - value) * MG_KG_TO_KG_HA)
        deficits[key] = need
        fert, share, density, unit = FERTILIZERS[key]
        dose = need / (share * density) if need else 0.0
        nutrients.append({
            "key": key, "title": title, "value": round(value, 1),
            "target": goal, "unit": "мг/кг", "supply_pct": round(ratio * 100),
            "verdict": _band(ratio), "need_kg_ha": round(need, 1),
            "fertilizer": fert if need >= 1 else "",
            "dose": f"{dose:.0f} {unit}" if need >= 1 else "",
        })

    ph = float(sa.get("ph", 6.5))
    if ph < 5.5:
        ph_verdict = "кислая — нужно известкование"
    elif ph < 6.0:
        ph_verdict = "слабокислая — известкование по потребности"
    elif ph <= 6.8:
        ph_verdict = "оптимальная"
    elif ph <= 7.4:
        ph_verdict = "нейтральная"
    else:
        ph_verdict = "щелочная — риск дефицита микроэлементов"

    humus = float(sa.get("humus_pct", 4.0))
    humus_verdict = ("низкое" if humus < 3.0 else "среднее" if humus < 4.0
                     else "повышенное" if humus < 6.0 else "высокое")

    parts = []
    for key in ("n", "p", "k"):
        item = next(x for x in nutrients if x["key"] == key)
        if item["need_kg_ha"] >= 10:
            parts.append(f"{item['fertilizer']} — {item['dose']} "
                         f"(дефицит {item['need_kg_ha']:.0f} кг д.в./га)")
    if ph < 5.5:
        parts.append("известкование: 4–6 т/га доломитовой муки под основную обработку")
    if not parts:
        parts.append("обеспеченность питания в норме — только поддерживающие подкормки")

    return {
        "sampled": sa.get("sampled"),
        "layer_cm": sa.get("layer_cm", 30),
        "ph": round(ph, 2),
        "ph_verdict": ph_verdict,
        "humus_pct": round(humus, 1),
        "humus_verdict": humus_verdict,
        "s_mg_kg": sa.get("s_mg_kg"),
        "nutrients": nutrients,
        "removal_kg_ha": {k: round(removal.get(k, 0) * yield_pot)
                          for k in ("n", "p", "k")},
        "recommendation": "; ".join(parts) + ".",
    }


# ---------------------------------------------------------- календарь ------
def _as_date(value):
    return date.fromisoformat(value) if isinstance(value, str) else value


def calendar(field, today):
    """Календарь фаз: что пройдено, что сейчас, когда уборка."""
    today = _as_date(today)
    phases = field.get("phases") or []

    if not phases:                                  # чистый пар: фаз нет
        return {
            "today": today.isoformat(),
            "current": {"key": "fallow", "title": "Чистый пар",
                        "start": None, "end": None, "status": "пар"},
            "phases": [],
            "harvest_date": None,
            "sowing_date": None,
            "days_to_harvest": None,
            "harvest_ready": False,
        }

    out = []
    for p in phases:
        start, end = _as_date(p["start"]), _as_date(p["end"])
        if today > end:
            status = "пройдена"
        elif start <= today <= end:
            status = "текущая"
        else:
            status = "предстоит"
        out.append({
            "key": p["key"], "title": p["title"],
            "start": p["start"], "end": p["end"], "status": status,
            "projected": start > today,
        })

    current = next((p for p in out if p["status"] == "текущая"), None)
    if current is None and out:
        # до всходов или после уборки — показываем ближайшую фазу, а не пустоту
        current = next((p for p in out if p["status"] == "предстоит"), out[-1])
    harvest = _as_date(field["harvest_date"]) if field.get("harvest_date") else None
    days_to_harvest = (harvest - today).days if harvest else None

    return {
        "today": today.isoformat(),
        "current": current,
        "phases": out,
        "harvest_date": field.get("harvest_date"),
        "sowing_date": field.get("sowing_date"),
        "days_to_harvest": days_to_harvest,
        "harvest_ready": bool(days_to_harvest is not None and days_to_harvest <= 14),
    }


# ------------------------------------------------------- вегетация --------
def _mix(f, soil, veg):
    return soil * (1.0 - f) + veg * f


def _indices(f):
    o = OPTICAL
    r = _mix(f, o["r_soil"], o["r_veg"])
    nir = _mix(f, o["nir_soil"], o["nir_veg"])
    g = _mix(f, o["g_soil"], o["g_veg"])
    b = _mix(f, o["b_soil"], o["b_veg"])
    return {
        "ndvi": round((nir - r) / (nir + r), 3),
        "evi": round(2.5 * (nir - r) / (nir + 6.0 * r - 7.5 * b + 1.0), 3),
        "savi": round(1.5 * (nir - r) / (nir + r + 0.5), 3),
        "gndvi": round((nir - g) / (nir + g), 3),
    }


def _solve_cover(target_ndvi):
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if _indices(mid)["ndvi"] < target_ndvi:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _canopy(field, when):
    """Проективное покрытие по доле прошедшего сезона (0…1)."""
    phases = field.get("phases") or []
    if not phases:
        return 0.05
    n = len(phases)
    for i, p in enumerate(phases):
        start, end = _as_date(p["start"]), _as_date(p["end"])
        if start <= when <= end:
            pos = (i + 0.5) / n
            idx = pos * (len(CANOPY_ANCHORS) - 1)
            lo = int(idx)
            hi = min(lo + 1, len(CANOPY_ANCHORS) - 1)
            frac = idx - lo
            return CANOPY_ANCHORS[lo] * (1 - frac) + CANOPY_ANCHORS[hi] * frac
        if when < start:
            pos = max(0.0, (i - 0.5) / n)
            idx = pos * (len(CANOPY_ANCHORS) - 1)
            lo = int(idx)
            return CANOPY_ANCHORS[lo]
    return CANOPY_ANCHORS[-1]


def vegetation(field, today, step=5):
    """Ряд индексов вегетации за сезон вокруг текущей даты."""
    today = _as_date(today)
    phases = field.get("phases") or []
    if not phases:
        return {"today": today.isoformat(), "current": _indices(_solve_cover(field.get("ndvi") or 0.3)),
                "points": [], "trend_ndvi": 0.0, "trend": "стабилен",
                "source": "модель (поле без посева)"}

    start = max(_as_date(field["sowing_date"]), today - timedelta(days=70))
    end = min(_as_date(field["harvest_date"]) if field.get("harvest_date") else today + timedelta(days=30),
              today + timedelta(days=35))

    ndvi_now = float(field.get("ndvi") or 0.5)
    cover_now = _solve_cover(ndvi_now)
    canopy_now = max(0.05, _canopy(field, today))
    k = min(0.97 / canopy_now, cover_now / canopy_now)

    points = []
    d = start
    while d <= end:
        cover = min(0.97, max(0.02, k * _canopy(field, d)))
        points.append({"date": d.isoformat(), **_indices(cover)})
        d += timedelta(days=step)

    current = _indices(cover_now)
    prev = points[-3] if len(points) >= 3 else (points[0] if points else current)
    trend = round(current["ndvi"] - prev["ndvi"], 3)
    return {
        "today": today.isoformat(),
        "current": current,
        "trend_ndvi": trend,
        "trend": "растёт" if trend > 0.02 else "падает" if trend < -0.02 else "стабилен",
        "points": points,
        "source": "модель по NDVI поля (замена спутниковым снимкам)",
    }


# ------------------------------------------------------ опрыскивания -----
def spraying_plan(field, today):
    today = _as_date(today)
    events = field.get("spraying") or []
    out = []
    for e in sorted(events, key=lambda x: x["date"]):
        day = _as_date(e["date"])
        if day < today:
            status, days = "проведено", (today - day).days
        elif day == today:
            status, days = "сегодня", 0
        else:
            status, days = "план", (day - today).days
        out.append({**e, "status": status, "days_left": days})

    done = [e for e in out if e["status"] == "проведено"]
    planned = [e for e in out if e["status"] != "проведено"]
    return {
        "events": out,
        "done": len(done),
        "planned": len(planned),
        "cost_done_rub_ha": round(sum(e["cost_rub_ha"] for e in done)),
        "cost_planned_rub_ha": round(sum(e["cost_rub_ha"] for e in planned)),
        "next": planned[0] if planned else None,
    }


# --------------------------------------------------- строка состояния ----
def state_row(field, risks, today):
    """Компактная строка для экрана «Состояние полей»."""
    today = _as_date(today)
    # если поле уже обогащено (dataset кэширует), не пересчитываем блоки
    agg = field.get("agronomy") or {}
    cal = agg.get("calendar") or calendar(field, today)
    soil = agg["soil_report"] if "soil_report" in agg else soil_report(field)
    sp = agg.get("spraying_plan") or spraying_plan(field, today)
    veg = agg.get("vegetation") or vegetation(field, today)

    bottleneck = None
    if soil:
        worst = min(soil["nutrients"], key=lambda x: x["supply_pct"])
        if worst["supply_pct"] < 90:            # «узкое место» — только если реально ниже нормы
            bottleneck = {"key": worst["key"], "title": worst["title"],
                          "supply_pct": worst["supply_pct"], "verdict": worst["verdict"]}

    nxt = sp.get("next")
    rot = field.get("rotation") or []
    nxt_rot = next((r for r in rot if r["status"] == "план"), None)

    max_risk = max(risks.values()) if risks else 0
    level = "critical" if max_risk >= 70 else "warning" if max_risk >= 40 else "ok"

    return {
        "field_id": field["id"],
        "name": field["name"],
        "region": field["region"],
        "settlement": field.get("settlement"),
        "culture": field["culture"],
        "culture_short": field.get("culture_short"),
        "area_ha": field["area_ha"],
        "status": level,
        "risks": risks,
        "lead_risk": max(risks, key=risks.get) if risks else None,
        "stage": cal["current"],
        "days_to_harvest": cal["days_to_harvest"],
        "harvest_date": field.get("harvest_date"),
        "sowing_date": field.get("sowing_date"),
        "ndvi": field.get("ndvi"),
        "ndvi_trend": veg["trend_ndvi"],
        "ndvi_verdict": veg["trend"],
        "npk": {n["key"]: n["supply_pct"] for n in soil["nutrients"]} if soil else None,
        "npk_bottleneck": bottleneck,
        "spraying": {"done": sp["done"], "planned": sp["planned"], "next": nxt},
        "rotation_next": {"year": nxt_rot["year"], "crop": nxt_rot["crop"]} if nxt_rot else None,
        "agronomist": field.get("agronomist"),
        "last_updated": field.get("last_updated"),
    }


# ------------------------------------------------------- техкарта ---------
TECH_COSTS = {"обработка почвы": 900, "удобрения": 4200, "посев": 2600, "уборка": 2800}


def tech_operations(field, today):
    """Технологическая карта поля: плановые работы + обработки + уборка."""
    today = _as_date(today)
    ops = []

    sowing = _as_date(field["sowing_date"]) if field.get("sowing_date") else None
    harvest = _as_date(field["harvest_date"]) if field.get("harvest_date") else None

    if sowing:
        ops.append({
            "date": (sowing - timedelta(days=21)).isoformat(),
            "kind": "обработка почвы",
            "title": "Предпосевная обработка",
            "detail": "культивация с боронованием, выравнивание",
            "cost_rub_ha": TECH_COSTS["обработка почвы"],
        })
        ops.append({
            "date": (sowing - timedelta(days=7)).isoformat(),
            "kind": "удобрения",
            "title": "Основное внесение NPK",
            "detail": "дозы — по агрохимическому обследованию",
            "cost_rub_ha": TECH_COSTS["удобрения"],
        })
        ops.append({
            "date": sowing.isoformat(),
            "kind": "посев",
            "title": "Посев",
            "detail": f"{field.get('variety', '')}, норма высева по культуре".strip(", "),
            "cost_rub_ha": TECH_COSTS["посев"],
        })

    for e in field.get("spraying") or []:
        ops.append({
            "date": e["date"],
            "kind": e["kind"],
            "title": e["product"],
            "detail": f"{e['dose']} · {e['target']}",
            "cost_rub_ha": e["cost_rub_ha"],
        })

    if harvest:
        ops.append({
            "date": harvest.isoformat(),
            "kind": "уборка",
            "title": "Уборка",
            "detail": "по готовности культуры, влажность по регламенту",
            "cost_rub_ha": TECH_COSTS["уборка"],
        })

    for op in ops:
        day = _as_date(op["date"])
        if day < today:
            op["status"], op["days_left"] = "проведено", (today - day).days
        elif day == today:
            op["status"], op["days_left"] = "сегодня", 0
        else:
            op["status"], op["days_left"] = "план", (day - today).days

    ops.sort(key=lambda x: x["date"])
    done = [o for o in ops if o["status"] == "проведено"]
    planned = [o for o in ops if o["status"] != "проведено"]
    return {
        "operations": ops,
        "done": len(done),
        "planned": len(planned),
        "cost_done_rub_ha": round(sum(o["cost_rub_ha"] for o in done)),
        "cost_planned_rub_ha": round(sum(o["cost_rub_ha"] for o in planned)),
    }


def enrich(field, today):
    """Дополняет поле агрономическими блоками (для карточки поля)."""
    today = _as_date(today)
    return {
        "soil_report": soil_report(field),
        "calendar": calendar(field, today),
        "vegetation": vegetation(field, today),
        "spraying_plan": spraying_plan(field, today),
        "tech_card": tech_operations(field, today),
    }
