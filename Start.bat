@echo off
chcp 65001 >nul
title AgroTech AI — Запуск
cd /d "%~dp0"

echo ============================================
echo   AgroTech AI — Запуск платформы
echo ============================================
echo.

REM Проверка наличия Python
where python >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python не найден в PATH.
    echo Установите Python 3.10+ с https://www.python.org/downloads/
    echo При установке отметьте галочку "Add Python to PATH".
    pause
    exit /b 1
)

REM Проверка виртуального окружения
if not exist venv\Scripts\activate.bat (
    echo Виртуальное окружение не найдено. Создаю...
    python -m venv venv --copies
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать venv.
        pause
        exit /b 1
    )
    echo Установка зависимостей ^(займёт 1-3 минуты^)...
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить зависимости.
        pause
        exit /b 1
    )
    echo.
)

REM Активация venv
call venv\Scripts\activate.bat

REM Проверка .env
if not exist .env (
    echo [ОШИБКА] Не найден файл .env
    echo Создайте его в папке проекта со строкой:
    echo ANYMODEL_API_KEY=sk-ваш-ключ
    pause
    exit /b 1
)

REM Генерация данных (только если ещё нет)
if not exist fields.json (
    echo [1/4] Генерация полей и обучающих данных...
    python data.py
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось сгенерировать данные.
        pause
        exit /b 1
    )
    echo.
) else (
    echo [1/4] Данные уже готовы ^(fields.json найден^).
)

REM Обучение модели (только если ещё нет)
if not exist risk_model.pkl (
    echo [2/4] Обучение ML-модели...
    python model.py
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось обучить модель.
        pause
        exit /b 1
    )
    echo.
) else (
    echo [2/4] Модель уже обучена ^(risk_model.pkl найден^).
)

REM Проверка погодного API
echo [3/4] Проверка подключения к Open-Meteo...
python -c "import weather; r = weather.get_forecast(45.035, 38.975, field={'id':'F-100','temperature':20,'moisture':60}); print('OK' if r.get('days') else 'НЕДОСТУПЕН (погода будет синтетической)')" 2>nul
echo.

REM Запуск сервера с автооткрытием браузера
echo [4/4] Запуск веб-сервера...
echo.
echo Сервер: http://localhost:8000
echo Для остановки нажмите Ctrl+C в этом окне.
echo.
start "" cmd /c "timeout /t 3 >nul && start http://localhost:8000"

python main.py

pause