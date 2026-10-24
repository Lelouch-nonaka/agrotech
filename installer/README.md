# Установка «Агро-Радара» на Windows

Установщик рассчитан на «закинул на другой ПК — само всё скачало и заработало».
Нужны только Windows и интернет. Права администратора **не требуются**.

## Как собрать дистрибутив

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\build.ps1
```

Результат: `installer\dist\AgroRadar-2.0.zip` (около 1,3 МБ). Внутри:

```
AgroRadar-2.0\
  app\            приложение (main.py, index.html, static\...)
  installer\      Install.cmd + install.ps1
```

`venv`, `shots`, `__pycache__` и `dist` в архив не попадают.

**Версия с ключом для куратора** (ИИ-Агроном работает сразу, без настройки):

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\build.ps1 -IncludeEnv
```

Флаг `-IncludeEnv` кладёт в архив `.env` с ключом AnyModel. **Такой архив нельзя
публиковать в открытом доступе** — передавайте только лично. Без флага `.env`
исключается, а на новом ПК ИИ-Агроном отвечает детерминированно (без LLM).

## Как поставить на другом ПК

1. Скопировать архив, **распаковать целиком** (правый клик → «Извлечь всё…»).
   Важно: рядом с папкой `installer` должна оказаться папка `app` — установщик
   берёт приложение из неё.
2. Открыть папку `AgroRadar-2.0\installer` и запустить **`Install.cmd`**
   (двойной клик; если SmartScreen предупредит — «Подробнее» → «Выполнить всё равно»).

Что произойдёт:

1. Приложение копируется в `%LOCALAPPDATA%\AgroRadar\app`.
2. Ищется Python 3.9+ (`py -3`, `python`, `python3`). Если его нет —
   скачивается официальный **Python 3.12 embeddable** с python.org,
   в него ставится pip.
3. Создаётся venv (если Python системный) и ставятся зависимости:
   `fastapi`, `uvicorn`, `scikit-learn`, `pandas`, `numpy`, `openai`,
   `python-dotenv` — это первое и единственное обращение к сети.
4. Создаются ярлыки «Агро-Радар» на рабочем столе и в меню «Пуск».
5. Приложение запускается: `http://127.0.0.1:8000/`.

Повторный запуск установщика обновляет файлы и не ломает установку.

### Параметры

| Параметр | Смысл |
|---|---|
| `-Port 8000` | порт сервера |
| `-InstallRoot D:\AgroRadar` | нестандартная папка установки |
| `-NoShortcuts` | не создавать ярлыки |
| `-DryRun` | показать план, ничего не менять |
| `-Uninstall` | удалить приложение и ярлыки |

Примеры:

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\install.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File .\installer\install.ps1 -Port 8090
powershell -ExecutionPolicy Bypass -File .\installer\install.ps1 -Uninstall
```

## Где что лежит после установки

| Путь | Содержимое |
|---|---|
| `%LOCALAPPDATA%\AgroRadar\app` | приложение |
| `%LOCALAPPDATA%\AgroRadar\venv` | окружение (если системный Python) |
| `%LOCALAPPDATA%\AgroRadar\python` | embeddable Python (если системного не было) |
| `%LOCALAPPDATA%\AgroRadar\AgroRadar.cmd` | лаунчер |
| `%LOCALAPPDATA%\AgroRadar\Uninstall.cmd` | удаление установки |
| `%LOCALAPPDATA%\AgroRadar\install.json` | отметка установки |

## Как удалить

Три способа, все равнозначные:

1. **Меню «Пуск»** → ярлык **«Удалить Агро-Радар»** (создаётся установщиком).
2. Запустить `%LOCALAPPDATA%\AgroRadar\Uninstall.cmd`.
3. Из архива: `installer\Uninstall.cmd` (или `install.ps1 -Uninstall`).

Удаляются ярлыки (рабочий стол, «Пуск», «Удалить»), останавливаются запущенные
процессы приложения и стирается `%LOCALAPPDATA%\AgroRadar` целиком. Файлы
приложения удаляются через пару секунд после выхода, чтобы не держать их
открытыми.

## Честные оговорки

- **Нужен интернет при установке.** Скачиваются Python (если нужно) и пакеты
  (~80–120 МБ). Без сети установка остановится с понятной ошибкой; тогда
  поставьте Python 3.9+ заранее — установщик его найдёт.
- **Первый запуск после установки** может занять несколько секунд: грузится
  модель рисков (4 МБ) и прогреваются библиотеки.
- **Антивирус/SmartScreen** может предупредить о неподписанном `.cmd`/`.ps1` —
  скрипты лежат рядом и их видно целиком; подпись для MVP не делалась.
- **Inno Setup (Setup.exe) не используется.** Установщик — PowerShell-скрипт
  с `.cmd`-обёрткой: так его проще читать и он не требует установленного
  компилятора. При желании `.exe` можно собрать Inno Setup 6, взяв за основу
  структуру из `build.ps1`.
- **Мобильные приложения** — см. `mobile\README.md`: PWA уже работает,
  нативные APK/IPA собираются через Capacitor на машине с Android SDK/Xcode.
