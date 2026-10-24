# Мобильное приложение «Агро-Радар» (Android / iOS)

Есть два пути, и они не исключают друг друга.

## 1. PWA — работает уже сейчас (без сборки)

Приложение отдаёт `manifest.webmanifest` и service worker: после первого
открытия интерфейс и последние данные доступны без сети.

1. Запустите сервер: `Start.bat` (или `venv\Scripts\python.exe main.py`).
2. На телефоне в той же Wi-Fi сети откройте `http://<IP-ПК>:8000/`.
3. iPhone/Safari: «Поделиться» → **«На экран "Домой"»**.
   Android/Chrome: меню → **«Установить приложение»**.

Ограничение: офлайн-кэш (service worker) включается только на `localhost` или
HTTPS. По локальной сети через `http://192.168.x.x` приложение работает, но без
офлайн-режима. Для полноценного офлайна — HTTPS (например, Tailscale или
локальный сертификат).

## 2. Нативная сборка через Capacitor (APK / IPA)

В этой папке — готовый каркас: `package.json`, `capacitor.config.json`, `www/`.

### Android (APK)

Нужны **JDK 17** и **Android SDK** (Android Studio), затем:

```bash
cd mobile
npm install
npx cap add android
# укажите адрес своего сервера в capacitor.config.json → server.url
npx cap sync android
npx cap open android      # Android Studio → Build → Build APK(s)
```

Либо из консоли, если Gradle настроен:

```bash
cd android
./gradlew assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
```

### iOS (IPA)

Только на macOS с Xcode:

```bash
cd mobile
npm install
npx cap add ios
npx cap sync ios
npx cap open ios          # Xcode → Signing → Run / Archive
```

### Важно про архитектуру

Приложение — тонкая оболочка вокруг сервера агронома (`server.url` в
`capacitor.config.json`). Данные, модель рисков и ИИ-Агроном живут на сервере,
поэтому:

- телефон и ПК должны быть в одной сети (или сервер доступен по интернету);
- при смене IP ПК поменяйте `server.url` и выполните `npx cap sync`;
- для «полностью в кармане» нужен либо локальный сервер на телефоне
  (Termux + Python — отдельная задача), либо перенос API в облако.

## Что проверено на этой машине

- PWA: манифест, иконки, service worker и офлайн-старт — проверены.
- Capacitor-каркас: файлы на месте, но **APK здесь не собирался**: на машине
  нет Android SDK и JDK 17 (есть только Java 8), а для iOS нужен macOS.
  Инструкции выше — для машины с установленным toolchain.
