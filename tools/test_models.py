# -*- coding: utf-8 -*-
"""Проверка LLM-моделей AnyModel на агрономическом вопросе.

Запуск:  python tools/test_models.py [--models m1,m2]
Печатает: статус, время ответа, есть ли русский текст, начало ответа.
Ключ берётся из .env, в вывод не попадает.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

CANDIDATES = [
    "am/nemotron-3-ultra-558b-a55b",
    "am/nemotron-3.5-lightning-30b-a3b",
    "am/nemotron-3-nano-omni-30b-a3b-reasoning",
    "am/gpt-oss-20b",
    "am/llama-3.2-11b-vision-instruct",
    "am/laguna-xs-2.1",
    "am/free",
    "am/nemotron-3-super-120b-a12b",
]

PROMPT = (
    "Поле озимой пшеницы, фаза «флаг-лист», 128 га, Черноземье. "
    "Риск вредителей 85% (клоп вредная черепашка), болезни 4%, засуха 3%. "
    "Сегодня 20 мая, через 3 дня ожидается дождь. "
    "Что делать в ближайшие 3 дня? Ответь тремя короткими пунктами по-русски, "
    "с конкретными препаратами и дозировками."
)


def load_env():
    path = BASE / ".env"
    key = None
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANYMODEL_API_KEY="):
                key = line.split("=", 1)[1].strip()
    return key or os.getenv("ANYMODEL_API_KEY")


def load_config():
    path = BASE / "config.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def call(model, key, base_url, timeout=90):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "Ты опытный агроном-консультант. Отвечай по-русски, конкретно."},
            {"role": "user", "content": PROMPT},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36"),
            "Authorization": f"Bearer {key}",
        },
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        elapsed = time.time() - started
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        usage = data.get("usage") or {}
        return {"ok": True, "elapsed": round(elapsed, 1), "text": text, "usage": usage}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "elapsed": round(time.time() - started, 1),
                "error": f"HTTP {exc.code}: {exc.read()[:700].decode('utf-8', 'replace')}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "elapsed": round(time.time() - started, 1),
                "error": f"{type(exc).__name__}: {exc}"}


def main():
    args = sys.argv[1:]
    models = CANDIDATES
    if "--models" in args:
        models = args[args.index("--models") + 1].split(",")

    key = load_env()
    if not key:
        print("НЕТ КЛЮЧА: заполните ANYMODEL_API_KEY в .env")
        return 1
    cfg = load_config()
    base_url = cfg.get("llm", {}).get("base_url", "https://anymodel.org/v1")
    print(f"Ключ: {key[:7]}…{key[-4:]}  База: {base_url}\n")

    for model in models:
        res = call(model, key, base_url)
        if not res["ok"]:
            print(f"[FAIL] {model}  {res['elapsed']}s  {res['error'][:160]}")
            continue
        text = " ".join(res["text"].split())
        cyr = any("а" <= ch.lower() <= "я" for ch in text)
        print(f"[OK]   {model}  {res['elapsed']}s  рус={cyr}  токены={res['usage'].get('total_tokens')}")
        print(f"       {text[:220]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
