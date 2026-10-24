"""
Прогноз агрономических рисков: RandomForest поверх агрометеорологических
признаков поля. Модель загружается с диска один раз за процесс — раньше
joblib.load() вызывался на каждый прогноз (4 МБ pickle на поле на запрос).
"""
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

BASE = Path(__file__).resolve().parent
MODEL_PATH = BASE / "risk_model.pkl"
DATA_PATH = BASE / "training_data.csv"

# Индекс фазы для модели: ключ фазы -> 0…1
STAGE_INDEX = {
    "emergence": 0.10, "tillering": 0.30, "dormancy": 0.20, "regrowth": 0.35,
    "leaves_4": 0.30, "leaves_5": 0.30, "leaves_8": 0.40, "leaves_9": 0.45,
    "branching": 0.40, "boot": 0.50, "closing": 0.50, "tassel": 0.60,
    "bud": 0.55, "flag": 0.60, "heading": 0.70, "flowering": 0.75,
    "pods": 0.80, "grain": 0.80, "fill": 0.85, "milk": 0.90,
    "root_growth": 0.60, "sugar": 0.85, "wax": 0.95, "ripening": 0.95,
    "harvest": 1.00, "fallow": 0.0,
}

_BUNDLE = None


def _bundle():
    """Ленивая загрузка модели: один раз на процесс."""
    global _BUNDLE
    if _BUNDLE is None:
        _BUNDLE = joblib.load(MODEL_PATH)
    return _BUNDLE


def train():
    print("Загружаю обучающие данные...")
    df = pd.read_csv(DATA_PATH)

    features = ["temperature", "moisture", "rainfall_7d", "ndvi", "stage_index"]
    X = df[features].values

    targets = {
        "disease": df["risk_disease"].values,
        "drought": df["risk_drought"].values,
        "pests": df["risk_pests"].values,
    }

    models = {}
    for name, y in targets.items():
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        clf = RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42, n_jobs=-1)
        clf.fit(X_train, y_train)
        acc = accuracy_score(y_test, clf.predict(X_test))
        print(f"  {name}: точность {acc:.2%}")
        models[name] = clf

    joblib.dump({"models": models, "features": features}, MODEL_PATH,
                compress=3)
    print("✓ Модель сохранена → risk_model.pkl")


def stage_index_of(field):
    phase = field.get("growth_phase") or {}
    key = phase.get("key")
    if key in STAGE_INDEX:
        return STAGE_INDEX[key]
    # старые данные: русское название фазы
    legacy = {"всходы": 0.1, "кущение": 0.3, "выход в трубку": 0.5,
              "колошение": 0.7, "цветение": 0.75, "созревание": 0.95,
              "уборка": 1.0}
    return legacy.get(str(field.get("growth_stage", "")).lower(), 0.3)


def predict(field):
    """Вероятности трёх рисков в процентах."""
    bundle = _bundle()
    X = np.array([[
        field["temperature"],
        field["moisture"],
        field["rainfall_7d"],
        field["ndvi"],
        stage_index_of(field),
    ]])

    result = {}
    for name, model in bundle["models"].items():
        proba = model.predict_proba(X)[0]
        result[name] = int(proba[1] * 100) if len(proba) > 1 else 0
    return result


if __name__ == "__main__":
    train()
