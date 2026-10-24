# -*- coding: utf-8 -*-
"""Генератор демо-набора полей «Агро-Радар» — РУСАГРО, Белгородская область.

Что внутри:
* 12 полей в четырёх реальных районах области (Корочанский, Белгородский,
  Валуйский, Алексеевский) — координаты у реальных сёл, полигоны и площади;
* агрохимический паспорт: N-NO3, P2O5, K2O, pH, гумус, сера (мг/кг, 0–30 см);
* севооборот на 7 лет с обоснованием чередования и чистым паром;
* календарь фенофаз с датами (посев, фазы, уборка);
* программа опрыскиваний: что, когда, чем, дозировка;
* NDVI и производные индексы (EVI/SAVI/GNDVI считаются в agronomy.py).

Демо-дата — 20 мая 2026: в одном кадре есть и только что посеянные поля,
и растущие, и пустое поле под посев.

Запуск:  python data.py
"""
import json
import math
import random
from datetime import date, datetime, time as dtime, timedelta

# Демо-дата: середина посевной-2026, когда видно все состояния полей
DEMO_DATE = date(2026, 5, 20)

random.seed(42)

# ---------------------------------------------------------------------------
# Культуры: агрономические нормы, фазы, программы обработок
# ---------------------------------------------------------------------------
CROPS = {
    "wheat_winter": {
        "title": "Озимая пшеница", "short": "Пшеница озим.",
        "variety": "Алексеевич",
        "sowing": "2025-09-05", "harvest": "2026-07-28",
        "yield_potential": 6.3, "price_rub_t": 15500,
        "base_temp": 0.0, "water_need_mm": 420,
        "optimal_temp": (15, 25), "optimal_moisture": (60, 75),
        "soil_target": {"n": 18, "p": 180, "k": 220},
        "removal_kg_t": {"n": 32, "p": 12, "k": 26},
        "rotation_return": 3,
        "good_after": ["soybean", "beet_sugar", "corn_grain", "barley_spring"],
        "bad_after": ["wheat_winter"],
        # фазы озимой пшеницы идут по календарю (осень + весна следующего года)
        "phases_calendar": [
            ("emergence", "Всходы", "09-12", "10-02", 0),
            ("tillering", "Кущение", "10-03", "11-15", 0),
            ("dormancy", "Зимний покой", "11-16", "03-10", 0),
            ("regrowth", "Отрастание", "03-11", "04-12", 1),
            ("boot", "Выход в трубку", "04-13", "05-08", 1),
            ("flag", "Флаг-лист", "05-09", "05-28", 1),
            ("heading", "Колошение", "05-29", "06-12", 1),
            ("flowering", "Цветение", "06-13", "06-25", 1),
            ("milk", "Молочная спелость", "06-26", "07-08", 1),
            ("wax", "Восковая спелость", "07-09", "07-20", 1),
            ("harvest", "Уборка", "07-21", "08-01", 1),
        ],
        "spray": [
            (0, "протравливание", "Сценик Комби", "0,50 л/т семян",
             "корневые гнили, плесневение семян", 380),
            (28, "гербицид", "Балерина Супер", "0,40 л/га",
             "двудольные сорняки (осенняя схема)", 1250),
            (196, "подкормка", "КАС-32", "200 л/га",
             "N 64 кг д.в./га, весеннее отрастание", 3400),
            (227, "гербицид", "Пума Плюс", "1,00 л/га",
             "овсюг, метлица, просовидные", 980),
            (240, "регулятор роста", "ЦеЦеЦе 750", "0,50 л/га",
             "короткостебельность, против полегания", 620),
            (247, "фунгицид", "Тилт Турбо", "0,50 л/га",
             "септориоз, мучнистая роса (T1)", 1450),
            (265, "инсектицид", "Борей", "0,15 л/га",
             "тля, трипс, клоп вредная черепашка", 540),
            (272, "фунгицид", "Амистар Трио", "0,70 л/га",
             "септориоз, бурая ржавчина (T2)", 1980),
            (292, "фунгицид", "Амистар Экстра", "0,80 л/га",
             "фузариоз колоса (T3, конец колошения)", 2100),
        ],
    },
    "barley_spring": {
        "title": "Ячмень яровой", "short": "Ячмень",
        "variety": "Надежный",
        "sowing": "2026-04-15", "harvest": "2026-07-16",
        "yield_potential": 5.2, "price_rub_t": 13800,
        "base_temp": 1.0, "water_need_mm": 340,
        "optimal_temp": (15, 24), "optimal_moisture": (60, 78),
        "soil_target": {"n": 16, "p": 160, "k": 200},
        "removal_kg_t": {"n": 26, "p": 11, "k": 22},
        "rotation_return": 3,
        "good_after": ["beet_sugar", "wheat_winter", "corn_grain"],
        "bad_after": ["barley_spring"],
        "phases_offset": [
            ("emergence", "Всходы", 8, 20),
            ("tillering", "Кущение", 21, 38),
            ("boot", "Выход в трубку", 39, 55),
            ("heading", "Колошение", 56, 70),
            ("flowering", "Цветение", 71, 82),
            ("milk", "Молочная спелость", 83, 97),
            ("wax", "Восковая спелость", 98, 110),
            ("harvest", "Уборка", 111, 120),
        ],
        "spray": [
            (0, "протравливание", "Селест Топ", "1,20 л/т семян",
             "корневые гнили, плесневение", 420),
            (20, "гербицид", "Линтур", "0,18 кг/га",
             "двудольные сорняки, осот", 860),
            (30, "подкормка", "КАС-32", "150 л/га",
             "N 48 кг д.в./га в фазу кущения", 2550),
            (45, "фунгицид", "Тилт Турбо", "0,50 л/га",
             "мучнистая роса, гельминтоспориоз", 1450),
            (60, "инсектицид", "Борей", "0,15 л/га",
             "тля, злаковая муха", 540),
            (75, "фунгицид", "Амистар Экстра", "0,60 л/га",
             "сетчатая пятнистость, ржавчина", 1750),
        ],
    },
    "beet_sugar": {
        "title": "Сахарная свёкла", "short": "Свёкла сах.",
        "variety": "Бриз",
        "sowing": "2026-04-05", "harvest": "2026-10-10",
        "yield_potential": 48.0, "price_rub_t": 5200,
        "base_temp": 5.0, "water_need_mm": 560,
        "optimal_temp": (15, 25), "optimal_moisture": (65, 80),
        "soil_target": {"n": 20, "p": 200, "k": 260},
        "removal_kg_t": {"n": 4.5, "p": 1.8, "k": 6.5},
        "rotation_return": 4,
        "good_after": ["wheat_winter", "barley_spring"],
        "bad_after": ["beet_sugar", "sunflower"],
        "phases_offset": [
            ("emergence", "Всходы", 10, 22),
            ("leaves_4", "2–4 пары листьев", 23, 45),
            ("leaves_8", "6–8 листьев", 46, 70),
            ("closing", "Смыкание рядков", 71, 100),
            ("root_growth", "Рост корнеплода", 101, 160),
            ("sugar", "Накопление сахара", 161, 200),
            ("harvest", "Уборка", 201, 215),
        ],
        "spray": [
            (0, "протравливание", "Крузер", "1,00 л/т семян",
             "корнеед, плесневение", 620),
            (18, "гербицид", "Бетанал Эксперт", "1,00 л/га",
             "двудольные сорняки, первая волна", 1650),
            (30, "гербицид", "Бетанал Макс Про", "1,00 л/га",
             "двудольные сорняки, вторая волна", 1650),
            (45, "инсектицид", "Калипсо", "0,15 л/га",
             "свекловичная блошка, долгоносик", 890),
            (60, "фунгицид", "Рекс Дуо", "0,60 л/га",
             "церкоспороз, мучнистая роса", 1750),
            (85, "фунгицид", "Рекс Дуо", "0,60 л/га",
             "церкоспороз (вторая обработка)", 1750),
        ],
    },
    "corn_grain": {
        "title": "Кукуруза на зерно", "short": "Кукуруза",
        "variety": "Воронежский 279",
        "sowing": "2026-05-02", "harvest": "2026-10-14",
        "yield_potential": 9.1, "price_rub_t": 14200,
        "base_temp": 10.0, "water_need_mm": 500,
        "optimal_temp": (20, 30), "optimal_moisture": (65, 80),
        "soil_target": {"n": 22, "p": 170, "k": 220},
        "removal_kg_t": {"n": 30, "p": 12, "k": 28},
        "rotation_return": 3,
        "good_after": ["wheat_winter", "barley_spring", "soybean", "beet_sugar"],
        "bad_after": ["corn_grain"],
        "phases_offset": [
            ("emergence", "Всходы", 10, 20),
            ("leaves_5", "3–5 листьев", 21, 35),
            ("leaves_9", "6–9 листьев", 36, 55),
            ("tassel", "Выметывание", 56, 70),
            ("flowering", "Цветение", 71, 85),
            ("grain", "Налив зерна", 86, 115),
            ("milk", "Молочная спелость", 116, 135),
            ("wax", "Восковая спелость", 136, 155),
            ("harvest", "Уборка", 156, 165),
        ],
        "spray": [
            (0, "протравливание", "Максим XL", "1,00 л/т семян",
             "плесневение, пузырчатая головня", 460),
            (22, "гербицид", "Майстер Пауэр", "0,15 кг/га",
             "страховой гербицид по всходам", 2650),
            (35, "подкормка", "КАС-32", "180 л/га",
             "N 58 кг д.в./га в фазу 6–9 листьев", 3050),
            (50, "инсектицид", "Кораген", "0,20 л/га",
             "стеблевой мотылёк, совка", 1240),
            (70, "фунгицид", "Амистар Экстра", "0,60 л/га",
             "гельминтоспориоз, фузариоз початка", 1750),
        ],
    },
    "sunflower": {
        "title": "Подсолнечник", "short": "Подсолнечник",
        "variety": "НК Неома",
        "sowing": "2026-05-08", "harvest": "2026-09-25",
        "yield_potential": 3.6, "price_rub_t": 31500,
        "base_temp": 8.0, "water_need_mm": 480,
        "optimal_temp": (20, 28), "optimal_moisture": (55, 70),
        "soil_target": {"n": 18, "p": 180, "k": 240},
        "removal_kg_t": {"n": 52, "p": 22, "k": 78},
        "rotation_return": 5,
        "good_after": ["wheat_winter", "barley_spring", "corn_grain"],
        "bad_after": ["sunflower", "beet_sugar"],
        "phases_offset": [
            ("emergence", "Всходы", 10, 20),
            ("leaves_4", "2–4 пары листьев", 21, 40),
            ("bud", "Бутонизация", 41, 60),
            ("flowering", "Цветение", 61, 80),
            ("fill", "Налив семян", 81, 105),
            ("ripening", "Созревание", 106, 125),
            ("harvest", "Уборка", 126, 140),
        ],
        "spray": [
            (0, "протравливание", "Крузер", "1,00 л/т семян",
             "плесневение, проволочник", 620),
            (15, "гербицид", "Гезагард", "3,00 л/га",
             "почвенный гербицид: двудольные и злаковые", 2450),
            (32, "гербицид", "Евро-Лайтнинг", "0,50 л/га",
             "послевсходовый гербицид (Clearfield)", 1980),
            (48, "инсектицид", "Каратэ Зеон", "0,20 л/га",
             "проволочник, тля", 780),
            (70, "фунгицид", "Пиктор", "0,75 л/га",
             "альтернариоз, фомоз", 1980),
        ],
    },
    "soybean": {
        "title": "Соя", "short": "Соя",
        "variety": "Опус",
        "sowing": "2026-05-12", "harvest": "2026-09-28",
        "yield_potential": 2.7, "price_rub_t": 34000,
        "base_temp": 10.0, "water_need_mm": 450,
        "optimal_temp": (20, 28), "optimal_moisture": (70, 85),
        "soil_target": {"n": 14, "p": 190, "k": 230},
        "removal_kg_t": {"n": 58, "p": 15, "k": 32},
        "rotation_return": 3,
        "good_after": ["wheat_winter", "barley_spring", "corn_grain"],
        "bad_after": ["soybean"],
        "phases_offset": [
            ("emergence", "Всходы", 10, 20),
            ("branching", "Ветвление", 21, 40),
            ("bud", "Бутонизация", 41, 55),
            ("flowering", "Цветение", 56, 75),
            ("pods", "Образование бобов", 76, 100),
            ("fill", "Налив бобов", 101, 120),
            ("ripening", "Созревание", 121, 135),
            ("harvest", "Уборка", 136, 145),
        ],
        "spray": [
            (0, "протравливание", "Максим XL", "1,00 л/т семян",
             "плесневение, фузариоз всходов", 460),
            (22, "гербицид", "Базагран", "2,00 л/га",
             "послевсходовый гербицид по двудольным", 1450),
            (38, "инсектицид", "Борей", "0,20 л/га",
             "клубеньковый долгоносик, тля", 620),
            (55, "фунгицид", "Амистар Экстра", "0,50 л/га",
             "септориоз, антракноз", 1550),
            (68, "инсектицид", "Каратэ Зеон", "0,20 л/га",
             "паутинный клещ, совка", 780),
        ],
    },
    "fallow": {
        "title": "Чистый пар", "short": "Пар",
        "variety": "—",
        "sowing": None, "harvest": None,
        "yield_potential": 0.0, "price_rub_t": 0,
        "base_temp": 5.0, "water_need_mm": 0,
        "optimal_temp": (0, 40), "optimal_moisture": (0, 100),
        "soil_target": {"n": 18, "p": 180, "k": 220},
        "removal_kg_t": {"n": 0, "p": 0, "k": 0},
        "rotation_return": 1,
        "good_after": [], "bad_after": [],
        "phases_offset": [],
        "spray": [],
    },
}

SOIL_BASE = {
    "чернозём типичный": {"ph": 6.4, "humus_pct": 5.6, "n": 17.0, "p": 205.0, "k": 235.0, "s": 11.0},
    "чернозём выщелоченный": {"ph": 6.0, "humus_pct": 5.0, "n": 15.0, "p": 178.0, "k": 205.0, "s": 9.5},
    "чернозём южный": {"ph": 6.8, "humus_pct": 4.0, "n": 12.0, "p": 150.0, "k": 180.0, "s": 8.0},
    "чернозём оподзоленный": {"ph": 5.8, "humus_pct": 4.4, "n": 13.0, "p": 162.0, "k": 188.0, "s": 8.5},
}

# Поля: реальные районы и сёла Белгородской области.
# id, имя, район, село, широта, долгота, площадь, культура, предшественник, почва, NDVI
FIELDS = [
    ("A-01", "Поле 1 · Бехтеевка", "Корочанский", "с. Бехтеевка",
     50.792, 36.721, 128.4, "wheat_winter", "соя", "чернозём типичный", 0.71),
    ("A-02", "Поле 2 · Погореловка", "Корочанский", "с. Погореловка",
     50.762, 36.687, 96.8, "beet_sugar", "озимая пшеница", "чернозём выщелоченный", 0.58),
    ("A-03", "Поле 3 · Яблоново", "Корочанский", "с. Яблоново",
     50.831, 36.694, 84.2, "barley_spring", "сахарная свёкла", "чернозём типичный", 0.64),
    ("B-01", "Поле 4 · Таврово", "Белгородский", "с. Таврово",
     50.531, 36.503, 142.6, "wheat_winter", "кукуруза", "чернозём типичный", 0.69),
    ("B-02", "Поле 5 · Никольское", "Белгородский", "с. Никольское",
     50.671, 36.552, 110.3, "corn_grain", "озимая пшеница", "чернозём выщелоченный", 0.61),
    ("B-03", "Поле 6 · Майский", "Белгородский", "п. Майский",
     50.523, 36.452, 76.5, "soybean", "озимая пшеница", "чернозём типичный", 0.55),
    ("C-01", "Поле 7 · Уразово", "Валуйский", "с. Уразово",
     50.131, 38.152, 152.8, "wheat_winter", "подсолнечник", "чернозём южный", 0.63),
    ("C-02", "Поле 8 · Шелаево", "Валуйский", "с. Шелаево",
     50.262, 38.052, 118.0, "sunflower", "озимая пшеница", "чернозём южный", 0.49),
    ("C-03", "Поле 9 · Валуйки", "Валуйский", "г. Валуйки",
     50.232, 38.081, 88.7, "beet_sugar", "ячмень", "чернозём южный", 0.56),
    ("D-01", "Поле 10 · Афанасьевка", "Алексеевский", "с. Афанасьевка",
     50.681, 38.601, 134.5, "corn_grain", "озимая пшеница", "чернозём типичный", 0.66),
    ("D-02", "Поле 11 · Иловка", "Алексеевский", "с. Иловка",
     50.572, 38.748, 92.3, "sunflower", "ячмень", "чернозём выщелоченный", 0.52),
    ("D-03", "Поле 12 · Пар", "Алексеевский", "с. Иловка",
     50.548, 38.702, 64.9, "fallow", "подсолнечник", "чернозём типичный", 0.28),
]

DISTRICTS = {
    "Корочанский": {"lat": 50.812, "lon": 36.748},
    "Белгородский": {"lat": 50.597, "lon": 36.588},
    "Валуйский": {"lat": 50.211, "lon": 38.106},
    "Алексеевский": {"lat": 50.630, "lon": 38.690},
}

M_PER_DEG_LAT = 111_320.0


def polygon(lat, lon, area_ha, rng):
    """Полигон поля: прямоугольник с неровными сторонами, повёрнутый по полю."""
    area_m2 = area_ha * 10_000.0
    aspect = rng.uniform(1.4, 2.3)
    w = math.sqrt(area_m2 / aspect)
    h = area_m2 / w
    pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    verts = []
    for i, (x, y) in enumerate(pts):
        verts.append((x, y))
        nx, ny = pts[(i + 1) % 4]
        if rng.random() < 0.7:                  # слегка «срезаем» угол
            t = rng.uniform(0.2, 0.45)
            verts.append((x + (nx - x) * t, y + (ny - y) * t))
    a = math.radians(rng.uniform(-25, 25))
    ca, sa = math.cos(a), math.sin(a)
    mlon = M_PER_DEG_LAT * math.cos(math.radians(lat))
    out = []
    for x, y in verts:
        rx, ry = x * ca - y * sa, x * sa + y * ca
        out.append([round(lat + ry / M_PER_DEG_LAT, 6), round(lon + rx / mlon, 6)])
    return out


def soil_analysis(soil, rng):
    base = SOIL_BASE.get(soil, SOIL_BASE["чернозём типичный"])
    jitter = lambda v, span: round(v * rng.uniform(1 - span, 1 + span), 1)
    return {
        "sampled": (DEMO_DATE - timedelta(days=rng.randint(20, 45))).isoformat(),
        "layer_cm": 30,
        "ph": round(base["ph"] + rng.uniform(-0.3, 0.3), 2),
        "humus_pct": jitter(base["humus_pct"], 0.10),
        "n_mg_kg": jitter(base["n"], 0.18),
        "p_mg_kg": jitter(base["p"], 0.12),
        "k_mg_kg": jitter(base["k"], 0.12),
        "s_mg_kg": round(base["s"] * rng.uniform(0.7, 1.3), 1),
    }


def build_phases(crop_key, sowing_date):
    """Календарь фенофаз: даты начала/конца каждой фазы и плановая уборка."""
    crop = CROPS[crop_key]
    if sowing_date is None:
        return []
    out = []
    if "phases_calendar" in crop:
        y = sowing_date.year
        for key, title, start_md, end_md, shift in crop["phases_calendar"]:
            sm, sd = map(int, start_md.split("-"))
            em, ed = map(int, end_md.split("-"))
            start = date(y + shift, sm, sd)
            end = date(y + shift, em, ed)
            if end < start:                     # переход через новый год
                end = date(y + shift + 1, em, ed)
            out.append({"key": key, "title": title,
                        "start": start.isoformat(), "end": end.isoformat()})
        return out
    for key, title, start_off, end_off in crop.get("phases_offset", []):
        out.append({"key": key, "title": title,
                    "start": (sowing_date + timedelta(days=start_off)).isoformat(),
                    "end": (sowing_date + timedelta(days=end_off)).isoformat()})
    return out


def spraying_program(crop_key, sowing_date, rng):
    crop = CROPS[crop_key]
    if sowing_date is None:
        return []
    events = []
    for offset, kind, product, dose, target, cost in crop.get("spray", []):
        day = sowing_date + timedelta(days=offset + rng.randint(-1, 1))
        events.append({
            "date": day.isoformat(),
            "kind": kind,
            "product": product,
            "dose": dose,
            "target": target,
            "cost_rub_ha": cost,
        })
    events.sort(key=lambda e: e["date"])
    return events


# --------------------------------------------------------------- севооборот --
ROTATION_CROPS = ["wheat_winter", "barley_spring", "corn_grain", "sunflower",
                  "soybean", "beet_sugar", "fallow"]


def _why(prev, crop, gap):
    p = CROPS[prev]["title"].lower() if prev in CROPS else "предшественник"
    if crop == "wheat_winter" and prev == "soybean":
        return "Пшеница после бобовых: 60–80 кг N/га последействия и рыхлый пахотный слой."
    if crop == "wheat_winter" and prev == "beet_sugar":
        return "После свёклы поле чистое от сорняков; уплотнение снимаем глубоким рыхлением."
    if crop == "wheat_winter" and prev == "fallow":
        return "Пшеница по чистому пару — максимальный запас влаги и азота под посев."
    if crop == "wheat_winter":
        return f"Озимая пшеница — основная товарная культура, возвращается через {gap} года после «{p}»."
    if crop == "soybean":
        return "Бобовые фиксируют 60–90 кг N/га и разрывают цикл корневых гнилей после зерновых."
    if crop == "sunflower":
        return f"Подсолнечник возвращают не раньше 5–7 лет: заразиха и фомоз (разрыв {gap} лет)."
    if crop == "beet_sugar":
        return f"Свёкла требует разрыва не менее 4 лет: нематода и церкоспороз (разрыв {gap} года)."
    if crop == "corn_grain":
        return f"Кукуруза использует последействие азота после «{p}» и хорошо дренирует почву."
    if crop == "barley_spring":
        return "Ячмень — страховочная культура: рано освобождает поле под подготовку озимых."
    if crop == "fallow":
        return "Чистый пар: накопление влаги, борьба с сорняками и очистка от патогенов."
    return f"Чередование с «{p}» выдерживает фитосанитарный разрыв."


def rotation_plan(current_crop, predecessor, seed, year_usage=None):
    """7 сезонов: текущий + 6 будущих, с чистым паром и обоснованием.

    `year_usage` — общий по хозяйству счётчик культур по годам: он разводит
    планы соседних полей, чтобы в одном сезоне не было «соя везде».
    """
    usage = year_usage if year_usage is not None else {}
    rng = random.Random(seed)
    seq = [(2026, current_crop)]
    for year in range(2027, 2033):
        prev = seq[-1][1]
        fallow_used = sum(1 for _, c in seq if c == "fallow")
        used_map = usage.setdefault(year, {})
        best, best_score = None, -1e9
        for cand in ROTATION_CROPS:
            rule = CROPS[cand]
            ret = rule["rotation_return"]
            recent = [c for _, c in seq[-ret:]]
            if cand in recent:
                continue
            if cand == "fallow":
                # чистый пар — не чаще одного раза за 7 лет и не подряд
                if fallow_used >= 1 or rng.random() > 0.12:
                    continue
            gap = ret
            score = 0.0
            score -= 1.1 * used_map.get(cand, 0)      # не сажать одно и то же везде
            if cand in rule["good_after"]:
                score += 2.5
            if prev in rule["bad_after"]:
                score -= 5.0
            if cand == "soybean" and "soybean" not in [c for _, c in seq[-4:]]:
                score += 1.2                          # бобовое звено, но не «соя везде»
            if cand not in [c for _, c in seq]:
                score += 0.8                          # разнообразие культур по годам
            if cand in ("wheat_winter", "barley_spring") and prev in ("sunflower", "beet_sugar", "soybean", "fallow"):
                score += 1.5
            if cand == "fallow" and prev != "wheat_winter":
                score += 0.5
            score += rng.uniform(0.0, 2.0)             # разные поля — разные планы
            if score > best_score:
                best, best_score = cand, score
        chosen = best if best else "barley_spring"
        used_map[chosen] = used_map.get(chosen, 0) + 1
        seq.append((year, chosen))

    out = []
    for i, (year, crop) in enumerate(seq):
        prev_crop = predecessor if i == 0 else seq[i - 1][1]
        last_seen = next((y for y, c in reversed(seq[:i]) if c == crop), None)
        gap = year - last_seen if last_seen else CROPS[crop]["rotation_return"]
        why = (f"Текущий сезон: {CROPS[crop]['title'].lower()} по предшественнику «{prev_crop}»."
               if i == 0 else _why(prev_crop, crop, gap))
        out.append({
            "year": year,
            "crop_key": crop,
            "crop": CROPS[crop]["title"],
            "status": "текущая" if i == 0 else "план",
            "why": why,
        })
    return out


def current_stage(phases, today):
    """Фаза на дату: пройдена / текущая / предстоит."""
    if not phases:
        return {"key": "fallow", "title": "Чистый пар", "start": None, "end": None,
                "status": "пар", "progress": 0}
    for i, p in enumerate(phases):
        start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
        if start <= today <= end:
            span = max(1, (end - start).days)
            prog = int((today - start).days / span * 100)
            return {**p, "status": "текущая", "progress": max(0, min(100, prog))}
        if today < start:
            return {"key": p["key"], "title": p["title"], "start": p["start"], "end": p["end"],
                    "status": "предстоит", "progress": 0}
    last = phases[-1]
    return {**last, "status": "пройдена", "progress": 100}


def build():
    fields = []
    rotation_usage = {}
    for idx, (fid, name, district, settlement, lat, lon, area, crop, pred,
              soil, ndvi) in enumerate(FIELDS):
        c = CROPS[crop]
        crop_rng = random.Random(1000 + idx)
        soil_rng = random.Random(2000 + idx)

        sowing = date.fromisoformat(c["sowing"]) if c["sowing"] else None
        phases = build_phases(crop, sowing)
        stage = current_stage(phases, DEMO_DATE)
        spray = spraying_program(crop, sowing, crop_rng)

        # текущие показатели на демо-дату (детерминированно)
        t_lo, t_hi = c["optimal_temp"]
        m_lo, m_hi = c["optimal_moisture"]
        temperature = round(crop_rng.uniform(t_lo - 3, t_hi + 2), 1)
        moisture = round(crop_rng.uniform(m_lo - 8, m_hi + 4), 1)
        rainfall = round(crop_rng.uniform(0, 18), 1)

        fields.append({
            "id": fid,
            "name": name,
            "region": f"{district} р-н",
            "district": district,
            "settlement": settlement,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "polygon": polygon(lat, lon, area, crop_rng),
            "area_ha": area,
            "culture": c["title"],
            "culture_key": crop,
            "culture_short": c["short"],
            "variety": c["variety"],
            "sowing_date": c["sowing"],
            "harvest_date": c["harvest"],
            "predecessor": pred,
            "growth_stage": stage["title"],
            "growth_phase": stage,
            "phases": phases,
            "soil": soil,
            "soil_analysis": soil_analysis(soil, soil_rng),
            "rotation": rotation_plan(crop, pred, 500 + idx, rotation_usage),
            "spraying": spray,
            "irrigation": False,
            "temperature": temperature,
            "moisture": moisture,
            "rainfall_7d": rainfall,
            "ndvi": ndvi,
            "optimal_temp": [t_lo, t_hi],
            "optimal_moisture": [m_lo, m_hi],
            "yield_potential": c["yield_potential"],
            "price_rub_t": c["price_rub_t"],
            "water_need_mm": c["water_need_mm"],
            "agronomist": {
                "Корочанский": "И. Петров",
                "Белгородский": "С. Кузьменко",
                "Валуйский": "А. Гринёв",
                "Алексеевский": "Д. Сотников",
            }[district],
            "last_updated": datetime.combine(DEMO_DATE, dtime(7, 40)).isoformat(),
        })

    payload = {
        "generated_for": "Агро-Радар · РУСАГРО · Белгородская область",
        "demo_date": DEMO_DATE.isoformat(),
        "crops": {k: {kk: vv for kk, vv in v.items() if kk not in ("phases_calendar", "phases_offset")}
                  for k, v in CROPS.items()},
        "fields": fields,
    }
    with open("fields.json", "w", encoding="utf-8") as fh:
        json.dump(fields, fh, ensure_ascii=False, indent=2)
    print(f"✓ {len(fields)} полей → fields.json")
    print(f"  площадь: {sum(f['area_ha'] for f in fields):.1f} га")
    print(f"  демо-дата: {DEMO_DATE}")
    return payload


def generate_training_data(n=5000):
    rows = []
    for _ in range(n):
        temp = random.uniform(5, 40)
        moisture = random.uniform(20, 95)
        rainfall = random.uniform(0, 50)
        ndvi = random.uniform(0.1, 0.95)
        stage_idx = random.uniform(0, 1)

        risk_disease = 1 if (moisture > 75 and 15 < temp < 28 and ndvi > 0.5) else 0
        risk_drought = 1 if (moisture < 45 and temp > 28 and rainfall < 10) else 0
        risk_pests = 1 if (temp > 22 and ndvi > 0.6 and 0.2 < stage_idx < 0.8) else 0

        if random.random() < 0.05:
            risk_disease = 1 - risk_disease
        if random.random() < 0.05:
            risk_drought = 1 - risk_drought
        if random.random() < 0.05:
            risk_pests = 1 - risk_pests

        rows.append({
            "temperature": round(temp, 1),
            "moisture": round(moisture, 1),
            "rainfall_7d": round(rainfall, 1),
            "ndvi": round(ndvi, 2),
            "stage_index": round(stage_idx, 2),
            "risk_disease": risk_disease,
            "risk_drought": risk_drought,
            "risk_pests": risk_pests,
        })
    return rows


if __name__ == "__main__":
    build()
    train = generate_training_data(5000)
    import pandas as pd
    pd.DataFrame(train).to_csv("training_data.csv", index=False)
    print(f"✓ {len(train)} строк обучающих данных → training_data.csv")
