# -*- coding: utf-8 -*-
"""Дымовой тест API «Агро-Радара» (сервер должен быть запущен).

Запуск:  python tools\\smoke_test.py [http://127.0.0.1:8000]
"""
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
problems = []


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def get_raw(path):
    with urllib.request.urlopen(BASE + path, timeout=40) as r:
        return r.status, r.read()


def post(path, payload):
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def check(name, cond, extra=""):
    print(f"[{'OK  ' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        problems.append(name)


def main():
    meta = get("/api/meta")
    check("health/meta", meta.get("product") == "Агро-Радар", meta.get("version"))
    check("демо-дата", meta.get("demo_date") == "2026-05-20", str(meta.get("demo_date")))

    fields = get("/api/fields")
    check("12 полей", len(fields) == 12, str(len(fields)))
    check("площадь 1290 га", abs(sum(f["area_ha"] for f in fields) - 1290.0) < 0.5)
    check("у всех есть риски и статус",
          all(set(f["risks"]) == {"disease", "drought", "pests"} and f["status"] for f in fields))
    check("статус = худший риск",
          all(f["status"] == ("critical" if f["max_risk"] >= 70 else
                              "warning" if f["max_risk"] >= 40 else "ok") for f in fields))
    check("координаты — Белгородская область",
          all(49.8 < f["lat"] < 51.5 and 35.5 < f["lon"] < 39.2 for f in fields))

    st = get("/api/fields/state")
    rows = st["rows"]
    check("состояние: 12 строк", len(rows) == 12, str(len(rows)))
    check("состояние: у всех фаза", all(r["stage"] and r["stage"].get("title") for r in rows))
    check("состояние: у всех NPK", all(r["npk"] and len(r["npk"]) == 3 for r in rows))
    order = {"critical": 3, "warning": 2, "ok": 1}
    keys = [(order[r["status"]], r["max_risk"]) for r in rows]
    check("состояние: сортировка «худшие сверху»", keys == sorted(keys, reverse=True))

    f = get("/api/fields/A-01")
    need = ("soil_report", "calendar", "vegetation", "spraying_plan", "rotation", "forecast")
    check("карточка A-01: все блоки", all(k in f and f[k] for k in need),
          ", ".join(k for k in need if not f.get(k)))

    soil = f["soil_report"]
    check("почва: три элемента", len(soil["nutrients"]) == 3,
          " / ".join(f"{n['key'].upper()} {n['supply_pct']}%" for n in soil["nutrients"]))
    check("почва: pH и гумус", soil["ph"] > 0 and soil["humus_pct"] > 0)
    check("почва: рекомендация по питанию", len(soil["recommendation"]) > 15)

    cal = f["calendar"]
    check("календарь: не меньше 9 фаз", len(cal["phases"]) >= 9, str(len(cal["phases"])))
    check("календарь: даты по возрастанию",
          [p["start"] for p in cal["phases"]] == sorted(p["start"] for p in cal["phases"]))
    check("календарь: уборка совпадает с полем", cal["harvest_date"] == f["harvest_date"])

    veg = f["vegetation"]
    check("индексы: NDVI/EVI/SAVI/GNDVI",
          all(k in veg["current"] for k in ("ndvi", "evi", "savi", "gndvi")))
    check("индексы: ряд ≥ 10 точек", len(veg["points"]) >= 10, str(len(veg["points"])))
    check("индексы: NDVI сходится с полем", abs(veg["current"]["ndvi"] - f["ndvi"]) < 0.01,
          f"{veg['current']['ndvi']} vs {f['ndvi']}")
    check("индексы: EVI ниже NDVI",
          all(p["evi"] < p["ndvi"] + 0.02 for p in veg["points"]))

    sp = f["spraying_plan"]
    check("обработки: есть план и факт", sp["done"] >= 1 and sp["planned"] >= 1,
          f"факт {sp['done']}, план {sp['planned']}")
    check("обработки: препарат и дозировка у всех",
          all(e["product"] and e["dose"] for e in sp["events"]))
    check("обработки: есть ближайшая", sp["next"] is not None)

    rot = f["rotation"]
    check("севооборот: 7 сезонов", len(rot) == 7, str(len(rot)))
    check("севооборот: годы подряд",
          [r["year"] for r in rot] == list(range(rot[0]["year"], rot[0]["year"] + 7)))
    check("севооборот: обоснование у каждого года", all(len(r["why"]) > 20 for r in rot))
    crops = [r["crop_key"] for r in rot]
    returns = {"wheat_winter": 3, "barley_spring": 3, "corn_grain": 3,
               "soybean": 3, "beet_sugar": 4, "sunflower": 5, "fallow": 1}
    violations = [c for i, c in enumerate(crops)
                  if c in crops[max(0, i - returns.get(c, 3)):i]]
    check("севооборот: правила возврата соблюдены", not violations, str(violations))

    fallow = get("/api/fields/D-03")
    check("чистый пар: фаза «Чистый пар»", fallow["growth_stage"] == "Чистый пар")
    check("чистый пар: фаз нет", len(fallow["calendar"]["phases"]) == 0)

    check("алерты", isinstance(get("/api/alerts"), list))
    check("статус погоды", get("/api/weather-status").get("source"))

    chat = post("/api/chat", {"field_id": "A-01", "question": "Что делать в ближайшие дни?"})
    check("чат: ответ не пустой", bool(chat.get("answer")), f"llm={chat.get('llm')}")

    report = post("/api/report", {"field_id": "A-01", "chat_history": []})
    html = report.get("html", "")
    check("отчёт: все разделы",
          all(x in html for x in ("Почва и питание", "Календарь фаз", "Севооборот", "Обработки")))

    status, _ = get_raw("/static/vendor/leaflet.js")
    check("статика: Leaflet локально", status == 200)
    _, body = get_raw("/manifest.webmanifest")
    check("PWA: манифест", b'"name"' in body)
    status, _ = get_raw("/sw.js")
    check("PWA: service worker", status == 200)

    print("\nИТОГ:", "все проверки пройдены" if not problems else f"проблемы: {problems}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
