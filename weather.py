"""
Погода: Open-Meteo (реальные данные) → синтетика (fallback).
Фоновая проверка каждые 30 секунд: если Open-Meteo стал доступен — переключаемся.
"""
import requests
import threading
import time
from datetime import datetime, timedelta


WEATHER_CODES = {
    0: ("Ясно", "☀️"), 1: ("Преимущ. ясно", "🌤"), 2: ("Переменная облачность", "⛅"),
    3: ("Пасмурно", "☁️"), 45: ("Туман", "🌫"), 48: ("Изморозь", "🌫"),
    51: ("Слабая морось", "🌦"), 53: ("Морось", "🌦"), 55: ("Сильная морось", "🌧"),
    61: ("Слабый дождь", "🌦"), 63: ("Дождь", "🌧"), 65: ("Сильный дождь", "⛈"),
    71: ("Слабый снег", "🌨"), 73: ("Снег", "❄️"), 75: ("Сильный снег", "❄️"),
    80: ("Ливни", "🌧"), 81: ("Сильные ливни", "⛈"), 82: ("Очень сильные ливни", "⛈"),
    95: ("Гроза", "⛈"), 96: ("Гроза с градом", "⛈"), 99: ("Сильная гроза с градом", "⛈"),
}


# ================== ГЛОБАЛЬНОЕ СОСТОЯНИЕ ==================
_openmeteo_available = None      # True / False / None (не проверено)
_last_check_time = 0             # unix timestamp последней проверки
_checks = 0                      # сколько раз проверяли (для логов)
_check_interval = 30
_lock = threading.Lock()


def _stable_seed(text):
    """Детерминированный seed: встроенный hash() меняется между запусками."""
    return sum((i + 1) * ord(ch) for i, ch in enumerate(str(text))) % 2**32


def _check_openmeteo_status():
    """Проверяет доступность Open-Meteo. Возвращает True/False."""
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {"latitude": 45.0, "longitude": 39.0, "current_weather": True}
        r = requests.get(url, params=params, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _background_checker():
    """Фоновый поток: проверяет доступность Open-Meteo каждые 30 секунд."""
    global _openmeteo_available, _last_check_time, _checks
    while True:
        available = _check_openmeteo_status()
        with _lock:
            prev = _openmeteo_available
            _openmeteo_available = available
            _last_check_time = time.time()
            _checks += 1
            checks = _checks

        # Логируем смену состояния и раз в 10 проверок (~5 минут)
        if prev is None:
            if available:
                print("[WEATHER] Первая проверка: Open-Meteo ДОСТУПЕН — используем реальные данные")
            else:
                print("[WEATHER] Первая проверка: Open-Meteo НЕДОСТУПЕН — переключаемся на синтетику")
        elif prev != available:
            if available:
                print("[WEATHER] ✓ Open-Meteo СНОВА ДОСТУПЕН — переключаемся на реальные данные")
            else:
                print("[WEATHER] ✗ Open-Meteo ОТКЛЮЧИЛСЯ — переключаемся на синтетику")
        elif checks % 10 == 0:
            status = "доступен" if available else "недоступен"
            print(f"[WEATHER] Плановая проверка: Open-Meteo {status}")

        time.sleep(_check_interval)


def start_background_checker(enabled: bool = True):
    """Запускает фоновый поток проверки. В демо-режиме не нужен."""
    if not enabled:
        print("[WEATHER] Демо-режим: используется детерминированный симулятор")
        return
    thread = threading.Thread(target=_background_checker, daemon=True)
    thread.start()
    print("[WEATHER] Фоновый мониторинг Open-Meteo запущен (каждые 30 секунд)")


def get_openmeteo_status():
    """Возвращает текущий статус: True / False / None."""
    with _lock:
        return _openmeteo_available


# ================== ИСТОЧНИКИ ==================

def _fetch_openmeteo(lat, lon):
    """Реальные данные из Open-Meteo."""
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat, "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,wind_speed_10m_max",
            "timezone": "Europe/Moscow", "forecast_days": 5,
        }
        r = requests.get(url, params=params, timeout=6)
        r.raise_for_status()
        data = r.json()
        daily = data.get("daily", {})
        days = []
        for i, date_str in enumerate(daily.get("time", [])):
            code = daily["weather_code"][i]
            desc, icon = WEATHER_CODES.get(code, ("—", "❓"))
            days.append({
                "date": date_str,
                "weekday": ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"][datetime.fromisoformat(date_str).weekday()],
                "temp_max": round(daily["temperature_2m_max"][i], 1),
                "temp_min": round(daily["temperature_2m_min"][i], 1),
                "precipitation": round(daily["precipitation_sum"][i], 1),
                "wind": round(daily["wind_speed_10m_max"][i], 1),
                "code": code, "description": desc, "icon": icon,
            })
        return days if days else None
    except Exception:
        return None


def _synthetic_smart(field: dict):
    """Умная синтетика на основе данных поля."""
    import random as rnd
    seed = _stable_seed(str(field.get("id", "F-100")) + str(datetime.now().timetuple().tm_yday))
    r = rnd.Random(seed)

    base_temp = field.get("temperature", 20)
    base_moisture = field.get("moisture", 60)
    rainfall_7d = field.get("rainfall_7d", 5)
    culture = field.get("culture", "")
    month = datetime.now().month

    season_shift = {1: -8, 2: -7, 3: -2, 4: 4, 5: 9, 6: 13, 7: 15, 8: 14, 9: 8, 10: 3, 11: -3, 12: -7}.get(month, 0)
    base_temp_season = base_temp + season_shift * 0.3

    rain_factor = min(1.0, rainfall_7d / 30)
    moisture_factor = max(0, (base_moisture - 55) / 45)
    precip_chance = min(0.85, 0.15 + rain_factor * 0.4 + moisture_factor * 0.3)

    if culture == "Пшеница озимая" and month in [11, 12, 1, 2, 3]:
        base_temp_season -= 2

    days = []
    today = datetime.now()
    cumulative_temp = base_temp_season

    for i in range(5):
        date = today + timedelta(days=i)
        drift = r.uniform(-1.5, 1.5)
        cumulative_temp += drift
        temp_max = cumulative_temp + r.uniform(3, 6)
        temp_min = cumulative_temp - r.uniform(3, 7)

        if r.random() < precip_chance:
            precipitation = round(r.uniform(0.3, 12.0), 1)
            if precipitation > 8: code = 65
            elif precipitation > 3: code = 63
            elif precipitation > 1: code = 61
            else: code = 51
        else:
            precipitation = 0.0
            code = r.choices([0, 1, 2, 3], weights=[40, 30, 20, 10])[0]

        desc, icon = WEATHER_CODES.get(code, ("—", "❓"))
        days.append({
            "date": date.strftime("%Y-%m-%d"),
            "weekday": ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"][date.weekday()],
            "temp_max": round(temp_max, 1),
            "temp_min": round(temp_min, 1),
            "precipitation": precipitation,
            "wind": round(r.uniform(1.5, 8.5), 1),
            "code": code, "description": desc, "icon": icon,
        })
    return days


def _synthetic_demo(field: dict, demo_date):
    """Детерминированный прогноз на демо-дату: повторяемый показ на защите."""
    import random as rnd

    r = rnd.Random(_stable_seed(str(field.get("id", "F-100")) + demo_date.isoformat()))
    base_temp = field.get("temperature", 20)
    month = demo_date.month
    season_shift = {1: -8, 2: -7, 3: -2, 4: 4, 5: 9, 6: 13, 7: 15,
                    8: 14, 9: 8, 10: 3, 11: -3, 12: -7}.get(month, 0)
    base_temp_season = base_temp + season_shift * 0.25
    precip_chance = min(0.8, 0.15 + (field.get("rainfall_7d", 5) / 30) * 0.5)

    days = []
    cumulative = base_temp_season
    for i in range(5):
        day = demo_date + timedelta(days=i)
        cumulative += r.uniform(-1.5, 1.5)
        tmax = cumulative + r.uniform(3, 6)
        tmin = cumulative - r.uniform(3, 7)
        if r.random() < precip_chance:
            precipitation = round(r.uniform(0.3, 12.0), 1)
            code = 65 if precipitation > 8 else 63 if precipitation > 3 else 61
        else:
            precipitation = 0.0
            code = r.choices([0, 1, 2, 3], weights=[40, 30, 20, 10])[0]
        desc, icon = WEATHER_CODES.get(code, ("—", "❓"))
        days.append({
            "date": day.isoformat(),
            "weekday": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][day.weekday()],
            "temp_max": round(tmax, 1),
            "temp_min": round(tmin, 1),
            "precipitation": precipitation,
            "wind": round(r.uniform(1.5, 8.5), 1),
            "code": code, "description": desc, "icon": icon,
        })
    return days


# ================== ПУБЛИЧНАЯ ФУНКЦИЯ ==================

def get_forecast(lat: float, lon: float, field: dict = None, demo_date=None) -> dict:
    """
    Возвращает прогноз.
    * demo_date задана — детерминированный демо-прогноз от этой даты;
    * иначе — Open-Meteo, а при его недоступности синтетика.
    """
    if demo_date is not None:
        return {
            "days": _synthetic_demo(field or {}, demo_date),
            "source": f"Демо-симулятор (дата {demo_date.isoformat()})",
            "synthetic": True,
        }

    status = get_openmeteo_status()

    # Попытка реальных данных (только если статус не False)
    if status is not False:
        days = _fetch_openmeteo(lat, lon)
        if days:
            return {"days": days, "source": "Open-Meteo (реальные данные)"}

    # Синтетика
    if field:
        return {
            "days": _synthetic_smart(field),
            "source": "Синтетический прогноз (Open-Meteo недоступен)",
            "synthetic": True,
        }
    return {"days": [], "error": "Нет данных для прогноза"}


if __name__ == "__main__":
    test_field = {
        "id": "F-100", "temperature": 24.8, "moisture": 54.8,
        "rainfall_7d": 3.5, "culture": "Пшеница озимая"
    }
    print("Проверка доступности Open-Meteo...")
    print(f"Open-Meteo: {'ДОСТУПЕН' if _check_openmeteo_status() else 'НЕДОСТУПЕН'}")
    print()

    r = get_forecast(45.035, 38.975, test_field)
    print(f"Источник: {r.get('source')}")
    for d in r["days"]:
        print(f"{d['date']} ({d['weekday']}): {d['icon']} {d['temp_min']}..{d['temp_max']}°C, осадки {d['precipitation']}мм")