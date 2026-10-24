# -*- coding: utf-8 -*-
"""«Агро-Радар» — backend (FastAPI).

Эндпоинты:
  GET  /api/meta                  — демо-дата, источник погоды, модель, версия
  GET  /api/fields                — поля со светофором (компактно)
  GET  /api/fields/state          — состояние всех посевов (экран «Поля»)
  GET  /api/fields/{id}           — полный разбор: риски, почва, календарь,
                                    индексы, обработки, севооборот, прогноз
  GET  /api/fields/{id}/soil      — агрохимия и дозы удобрений
  GET  /api/fields/{id}/rotation  — севооборот на 7 лет
  GET  /api/fields/{id}/calendar  — календарь фаз
  GET  /api/fields/{id}/spraying  — план/факт обработок
  GET  /api/fields/{id}/vegetation— NDVI / EVI / SAVI / GNDVI
  GET  /api/alerts                — поля с критичными рисками
  GET  /api/weather-status        — состояние источника погоды
  POST /api/chat                  — ИИ-Агроном
  POST /api/report                — HTML-отчёт по полю
"""
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agronomy
import model as ml
import weather as w

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except Exception:                                   # pragma: no cover
    pass

CONFIG = {}
_cfg_path = BASE / "config.json"
if _cfg_path.exists():
    CONFIG = json.loads(_cfg_path.read_text(encoding="utf-8"))

DEMO_MODE = bool(CONFIG.get("demo_mode"))
DEMO_DATE = date.fromisoformat(CONFIG["demo_date"]) if CONFIG.get("demo_date") else None
LLM_CFG = CONFIG.get("llm", {})
LLM_ENABLED = bool(LLM_CFG.get("enabled")) and bool(os.getenv("ANYMODEL_API_KEY"))

if LLM_ENABLED:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("ANYMODEL_API_KEY"),
                    base_url=LLM_CFG.get("base_url", "https://anymodel.org/v1"),
                    timeout=float(LLM_CFG.get("timeout_sec", 180)),
                    max_retries=1)
else:
    client = None

MODEL_NAME = LLM_CFG.get("model", "am/nemotron-3.5-lightning-30b-a3b")
FALLBACK_MODELS = [m for m in LLM_CFG.get("fallback_models", []) if m]

w.start_background_checker(enabled=not DEMO_MODE)

app = FastAPI(title="Агро-Радар", version="2.0")

# Статика (библиотеки, иконки) и PWA-файлы
STATIC_DIR = BASE / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(BASE / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(BASE / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})

# ------------------------------------------------------------------ кэш ----
_cache = {"mtime": None, "fields": [], "built": None}


def today():
    return DEMO_DATE if DEMO_MODE else date.today()


def _risk_level(risks):
    top = max(risks.values()) if risks else 0
    return "critical" if top >= 70 else "warning" if top >= 40 else "ok"


def _load_fields():
    path = BASE / "fields.json"
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        raw = json.loads(path.read_text(encoding="utf-8"))
        _cache["mtime"] = mtime
        _cache["fields"] = raw
        _cache["built"] = None
    return _cache["fields"]


def dataset():
    """Поля + риски + агрономия. Пересобирается при изменении fields.json."""
    if _cache["built"] is not None:
        return _cache["built"]
    day = today()
    rows = []
    for field in _load_fields():
        risks = ml.predict(field)
        rows.append({**field,
                     "risks": risks,
                     "max_risk": max(risks.values()) if risks else 0,
                     "status": _risk_level(risks),
                     "agronomy": agronomy.enrich(field, day)})
    _cache["built"] = rows
    return rows


def find_field(field_id):
    for f in dataset():
        if f["id"] == field_id:
            return f
    return None


def forecast_for(field):
    try:
        return w.get_forecast(field["lat"], field["lon"], field=field,
                              demo_date=DEMO_DATE if DEMO_MODE else None)
    except Exception as exc:                        # noqa: BLE001
        return {"days": [], "source": f"нет данных: {exc}", "synthetic": True}


def compact(field):
    """Поле без тяжёлых рядов — для дашборда, карты и списков."""
    agg = field["agronomy"]
    cal, sp, soil = agg["calendar"], agg["spraying_plan"], agg["soil_report"]
    veg = agg["vegetation"]
    npk = {n["key"]: n["supply_pct"] for n in soil["nutrients"]} if soil else None
    bottleneck = (min(soil["nutrients"], key=lambda n: n["supply_pct"])
                  if soil else None)
    nxt_rot = next(({"year": r["year"], "crop": r["crop"]}
                    for r in (field.get("rotation") or [])
                    if r["status"] == "план"), None)

    return {
        "id": field["id"],
        "name": field["name"],
        "region": field["region"],
        "settlement": field.get("settlement"),
        "district": field.get("district"),
        "lat": field["lat"],
        "lon": field["lon"],
        "polygon": field.get("polygon"),
        "area_ha": field["area_ha"],
        "culture": field["culture"],
        "culture_key": field.get("culture_key"),
        "culture_short": field.get("culture_short"),
        "variety": field.get("variety"),
        "growth_stage": field["growth_stage"],
        "stage": cal["current"],
        "sowing_date": field.get("sowing_date"),
        "harvest_date": field.get("harvest_date"),
        "days_to_harvest": cal["days_to_harvest"],
        "predecessor": field.get("predecessor"),
        "soil": field.get("soil"),
        "temperature": field["temperature"],
        "moisture": field["moisture"],
        "rainfall_7d": field["rainfall_7d"],
        "ndvi": field["ndvi"],
        "ndvi_trend": veg["trend_ndvi"],
        "ndvi_verdict": veg["trend"],
        "optimal_temp": field["optimal_temp"],
        "optimal_moisture": field["optimal_moisture"],
        "risks": field["risks"],
        "max_risk": field["max_risk"],
        "status": field["status"],
        "npk": npk,
        "npk_bottleneck": bottleneck,
        "spraying": {"done": sp["done"], "planned": sp["planned"], "next": sp["next"]},
        "rotation_next": nxt_rot,
        "agronomist": field.get("agronomist"),
        "last_updated": field.get("last_updated"),
    }


class ChatRequest(BaseModel):
    field_id: str
    question: str


class ReportRequest(BaseModel):
    field_id: str
    chat_history: list = []


# ================================================================ API =====

@app.get("/api/meta")
async def meta():
    fields = dataset()
    return {
        "product": "Агро-Радар",
        "version": "2.0",
        "demo_mode": DEMO_MODE,
        "demo_date": DEMO_DATE.isoformat() if DEMO_DATE else None,
        "today": today().isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "fields_total": len(fields),
        "area_ha": round(sum(f["area_ha"] for f in fields), 1),
        "llm_enabled": LLM_ENABLED,
        "llm_model": MODEL_NAME if LLM_ENABLED else None,
        "weather_source": "demo" if DEMO_MODE else ("openmeteo" if w.get_openmeteo_status() else "synthetic"),
    }


@app.get("/api/fields")
async def get_fields():
    return [compact(f) for f in dataset()]


@app.get("/api/fields/state")
async def fields_state():
    day = today()
    rows = []
    for f in dataset():
        rows.append(agronomy.state_row(f, f["risks"], day) | {
            "max_risk": f["max_risk"],
            "rotation_next": next(({"year": r["year"], "crop": r["crop"]}
                                   for r in (f.get("rotation") or [])
                                   if r["status"] == "план"), None),
        })
    order = {"critical": 3, "warning": 2, "ok": 1}
    rows.sort(key=lambda r: (-order[r["status"]], -r["max_risk"]))
    return {
        "meta": {
            "demo_date": DEMO_DATE.isoformat() if DEMO_DATE else None,
            "today": day.isoformat(),
            "fields": len(rows),
            "area_ha": round(sum(r["area_ha"] for r in rows), 1),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "rows": rows,
    }


@app.get("/api/rotation")
async def rotation_grid():
    """Севооборот всех полей одной сеткой: поля × годы."""
    rows, years = [], set()
    for f in dataset():
        rot = f.get("rotation") or []
        years.update(r["year"] for r in rot)
        rows.append({
            "field_id": f["id"], "name": f["name"], "culture": f["culture"],
            "culture_key": f.get("culture_key"), "region": f["region"],
            "area_ha": f["area_ha"],
            "years": [{"year": r["year"], "crop": r["crop"], "crop_key": r["crop_key"],
                       "status": r["status"], "why": r["why"]} for r in rot],
        })
    return {"years": sorted(years), "rows": rows,
            "meta": {"demo_date": DEMO_DATE.isoformat() if DEMO_DATE else None}}


@app.get("/api/fields/{field_id}")
def get_field(field_id: str):
    field = find_field(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    out = compact(field)
    agg = field["agronomy"]
    out["forecast"] = forecast_for(field)
    out["soil_report"] = agg["soil_report"]
    out["calendar"] = agg["calendar"]
    out["vegetation"] = agg["vegetation"]
    out["spraying_plan"] = agg["spraying_plan"]
    out["tech_card"] = agg["tech_card"]
    out["rotation"] = field.get("rotation")
    out["phases"] = field.get("phases")
    out["spraying_events"] = field.get("spraying")
    out["soil_analysis"] = field.get("soil_analysis")
    return out


def _block(field_id, key):
    field = find_field(field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    agg = field["agronomy"]
    mapping = {
        "soil": ("soil_report", agg["soil_report"]),
        "rotation": ("rotation", field.get("rotation")),
        "calendar": ("calendar", agg["calendar"]),
        "spraying": ("spraying", agg["spraying_plan"]),
        "vegetation": ("vegetation", agg["vegetation"]),
    }
    if key not in mapping:
        raise HTTPException(status_code=404, detail="Неизвестный блок")
    name, value = mapping[key]
    return {"field_id": field["id"], "name": field["name"], name: value}


@app.get("/api/fields/{field_id}/soil")
async def field_soil(field_id: str):
    return _block(field_id, "soil")


@app.get("/api/fields/{field_id}/rotation")
async def field_rotation(field_id: str):
    return _block(field_id, "rotation")


@app.get("/api/fields/{field_id}/calendar")
async def field_calendar(field_id: str):
    return _block(field_id, "calendar")


@app.get("/api/fields/{field_id}/spraying")
async def field_spraying(field_id: str):
    return _block(field_id, "spraying")


@app.get("/api/fields/{field_id}/vegetation")
async def field_vegetation(field_id: str):
    return _block(field_id, "vegetation")


@app.get("/api/alerts")
async def get_alerts():
    name_ru = {"disease": "болезни", "drought": "засуха", "pests": "вредители"}
    alerts = []
    for f in dataset():
        if f["status"] == "critical":
            lead = max(f["risks"], key=f["risks"].get)
            alerts.append({
                "field_id": f["id"], "field_name": f["name"],
                "culture": f["culture"], "risk_name": name_ru[lead],
                "risk_value": f["risks"][lead],
            })
    return alerts


@app.get("/api/weather-status")
async def weather_status():
    if DEMO_MODE:
        return {"openmeteo_available": False, "source": "Демо-симулятор (детерминированный)"}
    status = w.get_openmeteo_status()
    text = ("Open-Meteo (реальные данные)" if status is True else
            "Синтетика (Open-Meteo недоступен)" if status is False else "Проверка...")
    return {"openmeteo_available": status, "source": text}


# ------------------------------------------------------------- ИИ-Агроном --
SYSTEM_PROMPT = """Ты — агроном-консультант хозяйства в ЦЧР. Отвечай по-русски,
кратко и по делу — 3–5 пунктов, до 8 предложений, без таблиц и «воды».

Правила:
1. Опирайся только на факты из контекста: поле, фаза, риски, почва (NPK, pH),
   обработки, севооборот, прогноз погоды.
2. Препараты и дозировки бери ТОЛЬКО из блока «Обработки» контекста.
   Если подходящего препарата там нет — напиши «препарат подобрать по регламенту
   хозяйства», но не выдумывай названия и дозировки.
3. Учитывай погоду: не советуй опрыскивание перед дождём, при ветре или
   в жару; указывай ближайшее окно работ из прогноза.
4. Если риск высокий (≥70 %) — предупреди об этом первым пунктом.
5. Названия препаратов и дозировки копируй ТОЧНО из контекста, без переименований.
   Не перечисляй вредителей и болезни, которых нет в контексте.
6. В конце — одна строка «Контроль:» с тем, что проверить через 2–3 дня.
7. Пиши только по-русски, без английских слов и без рассуждений вслух."""


def _chat_context(field, forecast):
    agg = field["agronomy"]
    soil = agg["soil_report"]
    cal = agg["calendar"]
    sp = agg["spraying_plan"]
    veg = agg["vegetation"]["current"]

    soil_text = "\n".join(
        f"  - {n['title']}: {n['value']} из {n['target']} мг/кг ({n['supply_pct']}%) — {n['verdict']}"
        for n in soil["nutrients"]) if soil else "  (нет данных)"

    # Контекст сжат до важного: длинный промпт замедляет reasoning-модель
    phases = cal["phases"] if cal else []
    idx = next((i for i, p in enumerate(phases) if p["status"] != "пройдена"), max(0, len(phases) - 1))
    phases_text = "\n".join(
        f"  {p['title']}: {p['start']} — {p['end']} ({p['status']})"
        for p in phases[idx:idx + 3])

    events = sp["events"] if sp else []
    done = [e for e in events if e["status"] == "проведено"][-1:]
    planned = [e for e in events if e["status"] != "проведено"][:3]
    spray_text = "\n".join(
        f"  {e['date']} — {e['kind']} «{e['product']}», {e['dose']} ({e['status']})"
        for e in done + planned)

    rot = [r for r in (field.get("rotation") or [])]
    rot_text = " → ".join(f"{r['year']}: {r['crop']}" for r in rot[:3])

    forecast_text = "\n".join(
        f"  {d['date']} ({d['weekday']}): {d['icon']} {d['temp_min']}..{d['temp_max']}°C, "
        f"осадки {d['precipitation']} мм, ветер {d['wind']} м/с"
        for d in forecast.get("days", [])[:3])

    return f"""Поле {field['name']} ({field['id']}), {field['region']}, {field.get('settlement', '')}
Культура: {field['culture']} ({field.get('variety')}), площадь {field['area_ha']} га
Фаза: {field['growth_stage']}; посев {field.get('sowing_date')}, уборка {field.get('harvest_date')}
Предшественник: {field.get('predecessor')}; почва: {field.get('soil')}

Текущие показатели ({field['last_updated']}):
- температура {field['temperature']}°C (оптимум {field['optimal_temp'][0]}–{field['optimal_temp'][1]})
- влажность почвы {field['moisture']}% (оптимум {field['optimal_moisture'][0]}–{field['optimal_moisture'][1]})
- осадки 7 дней {field['rainfall_7d']} мм
- NDVI {field['ndvi']}, EVI {veg['evi']}, GNDVI {veg['gndvi']}

Риски (ML): болезни {field['risks']['disease']}%, засуха {field['risks']['drought']}%,
вредители {field['risks']['pests']}%

Почва (0–30 см, обследование {soil['sampled'] if soil else '—'}): pH {soil['ph'] if soil else '—'},
гумус {soil['humus_pct'] if soil else '—'}%
{soil_text}
Рекомендация по питанию: {soil['recommendation'] if soil else '—'}

Фазы развития:
{phases_text}

Обработки:
{spray_text}

Севооборот:
{rot_text}

Прогноз на 3 дня:
{forecast_text}"""


def _fallback_answer(field, question):
    """Ответ без LLM: короткая выжимка из данных, чтобы демо не падало."""
    risks = field["risks"]
    lead = max(risks, key=risks.get)
    name = {"disease": "болезни", "drought": "засуха", "pests": "вредители"}[lead]
    cal = field["agronomy"]["calendar"]
    sp = field["agronomy"]["spraying_plan"]
    soil = field["agronomy"]["soil_report"]
    worst = min(soil["nutrients"], key=lambda n: n["supply_pct"]) if soil else None

    lines = [f"**{field['name']}** — {field['culture'].lower()}, фаза «{field['growth_stage']}», "
             f"{field['area_ha']:.0f} га, {field['region']}.",
             f"Ведущий риск — **{name} {risks[lead]}%** "
             f"(болезни {risks['disease']}%, засуха {risks['drought']}%, вредители {risks['pests']}%)."]
    if cal and cal["days_to_harvest"] is not None:
        lines.append(f"До уборки {cal['days_to_harvest']} дн. ({field['harvest_date']}).")
    if worst:
        lines.append(f"Почва: {worst['title']} {worst['supply_pct']}% от нормы — "
                     f"{worst['verdict']}. {soil['recommendation']}")
    nxt = sp.get("next")
    if nxt:
        lines.append(f"Ближайшая обработка: {nxt['date']} — {nxt['kind']} "
                     f"«{nxt['product']}», {nxt['dose']} (через {nxt['days_left']} дн.).")
    lines.append("\n_Ответ собран из данных поля. LLM-слой отключён или недоступен._")
    return "\n".join(lines)


ALLOWED_LATIN = {"ndvi", "evi", "savi", "gndvi", "npk", "ph", "gdd", "et0", "roi"}
_FOREIGN_RE = re.compile(r"[\u0600-\u06FF\u4E00-\u9FFF\uAC00-\uD7AF]")


def _clean_answer(text):
    """Убирает случайные иероглифы/арабские символы, схлопывает пробелы."""
    cleaned = _FOREIGN_RE.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _answer_ok(text):
    """Ответ пригоден: длинный, по-русски, без иероглифов и английских слов."""
    if not text or len(text) < 120:
        return False
    cyr = len(re.findall(r"[А-Яа-яЁё]", text))
    leaks = [w for w in re.findall(r"[A-Za-z]{3,}", text) if w.lower() not in ALLOWED_LATIN]
    if len(leaks) > 2:                              # единичные вставки — не брак
        return False
    return cyr >= 80


def _generate_answer(context, question):
    """Перебирает модели, пока не получится нормальный русский ответ."""
    extra = {}
    effort = LLM_CFG.get("reasoning_effort")
    if effort:
        extra["extra_body"] = {"reasoning_effort": effort}
    temp = LLM_CFG.get("temperature")
    if temp is not None:
        extra["temperature"] = float(temp)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{context}\n\nВопрос агронома: {question}"}]
    last_error = None
    # основная модель + один фолбэк: каждая попытка ~20–40 с, больше не нужно
    plan = [MODEL_NAME] + FALLBACK_MODELS[:1]
    for attempt, model in enumerate(plan, 1):
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, **extra)
            answer = _clean_answer((response.choices[0].message.content or "").strip())
            if _answer_ok(answer):
                return answer, model
            cyr = len(re.findall(r"[А-Яа-яЁё]", answer))
            foreign = len(re.findall(r"[A-Za-z\u0600-\u06FF\u4E00-\u9FFF\uAC00-\uD7AF]", answer))
            print(f"[LLM] {model} попытка {attempt}: отклонён (len={len(answer)}, "
                  f"кир={cyr}, иностр={foreign})")
        except Exception as exc:                    # noqa: BLE001
            last_error = exc
            print(f"[LLM] {model} попытка {attempt}: {type(exc).__name__}: {exc}")
    return None, last_error


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Синхронный эндпоинт: LLM-запрос уходит в threadpool и не блокирует сервер."""
    field = find_field(req.field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    forecast = forecast_for(field)
    context = _chat_context(field, forecast)

    if not LLM_ENABLED:
        return {"answer": _fallback_answer(field, req.question),
                "field_id": field["id"], "llm": False}

    answer, info = _generate_answer(context, req.question)
    if answer:
        return {"answer": answer, "field_id": field["id"],
                "llm": True, "model": info}

    print("[LLM] нет пригодного ответа, отдаю детерминированный:", info)
    return {"answer": _fallback_answer(field, req.question)
            + f"\n\n_LLM недоступен: {type(info).__name__}_",
            "field_id": field["id"], "llm": False}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Тот же ответ, но текст отдаётся по мере генерации (plain-text stream)."""
    field = find_field(req.field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    forecast = forecast_for(field)
    context = _chat_context(field, forecast)

    def generate():
        if not LLM_ENABLED:
            yield _fallback_answer(field, req.question)
            return

        # Reasoning-модели в потоке иногда отдают «размышления» вместо ответа.
        # Берём проверенный готовый ответ и печатаем его плавно.
        answer, _info = _generate_answer(context, req.question)
        if not answer:
            answer = _fallback_answer(field, req.question)

        step = 28
        for i in range(0, len(answer), step):
            yield answer[i:i + step]
            time.sleep(0.012)

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- отчёт ----
def _report_html(field, forecast, chat_history):
    agg = field["agronomy"]
    soil, cal, sp = agg["soil_report"], agg["calendar"], agg["spraying_plan"]
    risks = field["risks"]
    removal = soil["removal_kg_ha"] if soil else {"n": "—", "p": "—", "k": "—"}

    def metric(label, value, cls=""):
        return (f'<div class="metric {cls}"><div class="label">{label}</div>'
                f'<div class="value">{value}</div></div>')

    soil_rows = "".join(
        f"<tr><td>{n['title']}</td><td>{n['value']} / {n['target']} {n['unit']}</td>"
        f"<td>{n['supply_pct']}%</td><td>{n['verdict']}</td><td>{n['dose'] or '—'}</td></tr>"
        for n in soil["nutrients"]) if soil else ""

    phase_rows = "".join(
        f"<tr><td>{p['title']}</td><td>{p['start']} — {p['end']}</td>"
        f"<td>{p['status']}</td></tr>" for p in cal["phases"]) if cal else ""

    spray_rows = "".join(
        f"<tr><td>{e['date']}</td><td>{e['kind']}</td><td>{e['product']}</td>"
        f"<td>{e['dose']}</td><td>{e['target']}</td><td>{e['status']}</td></tr>"
        for e in sp["events"]) if sp else ""

    rot_rows = "".join(
        f"<tr><td>{r['year']}</td><td>{r['crop']}</td><td>{r['why']}</td></tr>"
        for r in (field.get("rotation") or []))

    forecast_rows = "".join(
        f"<tr><td>{d['date']} ({d['weekday']})</td><td>{d['icon']} {d['description']}</td>"
        f"<td>{d['temp_min']}..{d['temp_max']}°C</td><td>{d['precipitation']} мм</td>"
        f"<td>{d['wind']} м/с</td></tr>" for d in forecast.get("days", []))

    chat_html = "".join(
        f'<div class="msg {"user" if m.get("role") == "user" else "ai"}">{m.get("text", "")}</div>'
        for m in chat_history)

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Отчёт: {field['name']}</title>
<style>
 body {{ font-family: 'Segoe UI', sans-serif; background:#fff; color:#222; max-width:960px;
        margin:40px auto; padding:20px; }}
 h1 {{ color:#2e7d32; border-bottom:3px solid #2e7d32; padding-bottom:10px; }}
 h2 {{ color:#2e7d32; margin-top:30px; border-bottom:1px solid #ddd; padding-bottom:6px; }}
 .meta {{ color:#666; font-size:14px; margin-bottom:20px; }}
 .metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:20px 0; }}
 .metric {{ background:#f5f5f5; padding:14px; border-radius:8px; border-left:4px solid #4CAF50; }}
 .metric .label {{ font-size:11px; color:#888; text-transform:uppercase; }}
 .metric .value {{ font-size:22px; font-weight:600; margin-top:4px; }}
 .risk-high {{ border-left-color:#f44336 !important; }}
 .risk-mid {{ border-left-color:#ff9800 !important; }}
 table {{ width:100%; border-collapse:collapse; margin:15px 0; }}
 th, td {{ border:1px solid #ddd; padding:8px 10px; text-align:left; font-size:13px; }}
 th {{ background:#2e7d32; color:#fff; }}
 tr:nth-child(even) {{ background:#f9f9f9; }}
 .msg {{ padding:12px 16px; border-radius:8px; margin:8px 0; font-size:14px; }}
 .msg.user {{ background:#e3f2fd; margin-left:40px; }}
 .msg.ai {{ background:#f5f5f5; border-left:4px solid #4CAF50; }}
 .footer {{ margin-top:40px; text-align:center; color:#888; font-size:12px;
            border-top:1px solid #ddd; padding-top:20px; }}
</style></head><body>
<h1>📊 Отчёт по полю: {field['name']}</h1>
<div class="meta">
 <b>ID:</b> {field['id']} • <b>Район:</b> {field['region']} • <b>Село:</b> {field.get('settlement','—')}<br>
 <b>Культура:</b> {field['culture']} ({field.get('variety','—')}) • <b>Площадь:</b> {field['area_ha']} га •
 <b>Фаза:</b> {field['growth_stage']}<br>
 <b>Посев:</b> {field.get('sowing_date','—')} • <b>Уборка:</b> {field.get('harvest_date','—')} •
 <b>Отчёт:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}
</div>

<h2>🌡 Текущие показатели</h2>
<div class="metrics">
 {metric("Температура", f"{field['temperature']}°C")}
 {metric("Влажность", f"{field['moisture']}%")}
 {metric("Осадки 7д", f"{field['rainfall_7d']} мм")}
 {metric("NDVI", field['ndvi'])}
</div>

<h2>⚠️ Прогноз рисков (ML)</h2>
<div class="metrics">
 {metric("Болезни", f"{risks['disease']}%", "risk-high" if risks['disease'] >= 70 else "risk-mid" if risks['disease'] >= 40 else "")}
 {metric("Засуха", f"{risks['drought']}%", "risk-high" if risks['drought'] >= 70 else "risk-mid" if risks['drought'] >= 40 else "")}
 {metric("Вредители", f"{risks['pests']}%", "risk-high" if risks['pests'] >= 70 else "risk-mid" if risks['pests'] >= 40 else "")}
 {metric("Статус", {"critical": "КРИТИЧНО", "warning": "ВНИМАНИЕ", "ok": "НОРМА"}[field['status']])}
</div>

<h2>🧪 Почва и питание (0–30 см)</h2>
<div class="meta">Обследование: {soil['sampled'] if soil else '—'} • pH {soil['ph'] if soil else '—'} •
 гумус {soil['humus_pct'] if soil else '—'}% • вынос: N {removal['n']} /
 P {removal['p']} / K {removal['k']} кг/га</div>
<table><thead><tr><th>Элемент</th><th>Факт / цель</th><th>Обеспеченность</th>
<th>Оценка</th><th>Доза удобрения</th></tr></thead><tbody>{soil_rows}</tbody></table>
<p><b>Рекомендация:</b> {soil['recommendation'] if soil else '—'}</p>

<h2>📅 Календарь фаз</h2>
<table><thead><tr><th>Фаза</th><th>Даты</th><th>Статус</th></tr></thead>
<tbody>{phase_rows}</tbody></table>

<h2>🧴 Обработки</h2>
<table><thead><tr><th>Дата</th><th>Вид</th><th>Препарат</th><th>Дозировка</th>
<th>Цель</th><th>Статус</th></tr></thead><tbody>{spray_rows}</tbody></table>

<h2>🔁 Севооборот на 7 лет</h2>
<table><thead><tr><th>Год</th><th>Культура</th><th>Обоснование</th></tr></thead>
<tbody>{rot_rows}</tbody></table>

<h2>🌤 Прогноз на 5 дней</h2>
<table><thead><tr><th>Дата</th><th>Погода</th><th>Температура</th><th>Осадки</th>
<th>Ветер</th></tr></thead><tbody>{forecast_rows}</tbody></table>
<div class="meta">Источник: {forecast.get('source', '—')}</div>

<h2>💬 Консультации ИИ-Агронома</h2>
{chat_html or '<p style="color:#888">Диалогов пока не было.</p>'}

<div class="footer">Отчёт сгенерирован «Агро-Радар» • {datetime.now().strftime('%d.%m.%Y %H:%M')}<br>
Прогноз рисков: Random Forest</div>
</body></html>"""


@app.post("/api/report")
def generate_report(req: ReportRequest):
    field = find_field(req.field_id)
    if not field:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    return {"html": _report_html(field, forecast_for(field), req.chat_history)}


@app.get("/", response_class=HTMLResponse)
async def root():
    return (BASE / "index.html").read_text(encoding="utf-8")


def _lan_ips():
    """IPv4-адреса машины в локальной сети — чтобы открыть прототип с телефона."""
    import socket
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))       # пакеты не отправляются, выбирается маршрут
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue                      # loopback и link-local не нужны
            ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


if __name__ == "__main__":
    import uvicorn
    app_cfg = CONFIG.get("app", {})
    port = int(app_cfg.get("port", 8000))
    host = app_cfg.get("host", "0.0.0.0")
    print(f"\n  Локально:  http://127.0.0.1:{port}/")
    for ip in _lan_ips():
        print(f"  Телефон:   http://{ip}:{port}/   (та же Wi-Fi, разрешить порт в брандмауэре)")
    print()
    uvicorn.run(app, host=host, port=port)
