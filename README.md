# 📈 T-Invest Telegram Bot

Многопользовательский Telegram-бот для мониторинга портфеля и выплат в **Т-Инвестициях** через официальный T-Invest API.

Бот позволяет в реальном времени отслеживать структуру портфеля, ближайшие купоны и дивиденды, а также строить годовой прогноз выплат.

---

## ✨ Возможности

* 📊 `/balance` — общая стоимость портфеля и разбивка по категориям: акции, облигации, фонды (ETF), кэш.
* 🗓 `/upcoming` — календарь ожидаемых выплат (купоны и дивиденды) на ближайшие 30 дней.
* 📈 `/report` — сводный прогноз доходности портфеля на 365 дней вперед с рейтингом топ-25 активов.
* 💵 `/rates` — актуальные курсы валют (USD, EUR, CNY) с Мосбиржи и ЦБ РФ.
* ⭐️ `/donate` — поддержка автора через Telegram Stars.
* ⚙️ `/admin` — статистика пользователей и активности (доступно только администратору).
* 🔒 `/logout` — удаление токена пользователя из базы данных.

### 🛡 Безопасность
* Бот запрашивает у пользователей токен Т-Инвестиций исключительно с правами **«Только чтение» (Read-Only)**. Совершать сделки или выводить средства через этот токен технически невозможно.
* Токены пользователей шифруются в локальной базе данных SQLite алгоритмом **Fernet (AES-128-CBC)** с уникальным сгенерированным секретным ключом.

---

## 🚀 Установка на сервер в 1 команду (Ubuntu / Debian)

Подключитесь к вашему VPS/VDS-серверу по SSH и выполните одну команду:

```bash
curl -sSL https://raw.githubusercontent.com/alimsabirov409-prog/tinvest-bot/main/install.sh | sudo bash
```

Скрипт автоматически:
1. Установит необходимые пакеты ОС (`python3`, `pip`, `git`, `curl`).
2. Запросит `TELEGRAM_TOKEN` и ваш `ADMIN_ID` (если они не переданы заранее).
3. Создаст изолированное виртуальное окружение `venv` и установит зависимости.
4. Сгенерирует надежный ключ шифрования `ENCRYPTION_KEY` и запишет `.env`.
5. Создаст, активирует и запустит фоновую службу `systemd` (`tinvestbot.service`), которая будет автоматически перезапускаться при перезагрузке сервера.

### ⚡ Установка в одну строку без диалогов (Non-interactive)
Если вы хотите передать переменные сразу:

```bash
sudo TELEGRAM_TOKEN="ВАШ_ТЕЛЕГРАМ_ТОКЕН" ADMIN_ID="ВАШ_АДМИН_ID" bash <(curl -sSL https://raw.githubusercontent.com/alimsabirov409-prog/tinvest-bot/main/install.sh)
```

---

## 📋 Подготовка перед установкой

1. **Токен Telegram-бота**:
   * Напишите [@BotFather](https://t.me/BotFather) в Telegram.
   * Отправьте `/newbot`, укажите имя и юзернейм бота.
   * Скопируйте полученный токен (вида `123456789:ABCdefGHI...`).

2. **Ваш числовой ID в Telegram (ADMIN_ID)**:
   * Напишите [@userinfobot](https://t.me/userinfobot) в Telegram.
   * Скопируйте числовой `Id` (например, `2126534573`).

3. **Токен Т-Инвестиций (для пользователей бота)**:
   * Откройте [Личный кабинет Т-Инвестиций](https://www.tbank.ru/invest/settings/api/).
   * Нажмите «Выпустить токен для T-Invest API».
   * Выберите права: **«Только чтение»**.
   * После старта бота отправьте этот токен боту в чат.

---

## 🛠 Управление ботом на сервере

После установки бот работает как служба systemd с именем `tinvestbot`:

* **Проверить статус**:
  ```bash
  sudo systemctl status tinvestbot
  ```
* **Смотреть логи в реальном времени**:
  ```bash
  sudo journalctl -u tinvestbot -f
  ```
* **Перезапустить бота**:
  ```bash
  sudo systemctl restart tinvestbot
  ```
* **Остановить бота**:
  ```bash
  sudo systemctl stop tinvestbot
  ```
* **Запустить снова**:
  ```bash
  sudo systemctl start tinvestbot
  ```

---

## 🔄 Как обновить бота на сервере

Чтобы обновить бота до последней версии с GitHub:

```bash
cd /opt/tinvest_bot
sudo git pull
sudo ./venv/bin/pip install --upgrade -r requirements.txt
sudo systemctl restart tinvestbot
```

---

## 💻 Локальный запуск для разработки

1. Склонируйте репозиторий:
   ```bash
   git clone https://github.com/alimsabirov409-prog/tinvest-bot.git
   cd tinvest-bot
   ```
2. Создайте виртуальное окружение:
   ```bash
   python -m venv venv
   source venv/bin/activate  # На Linux/macOS
   # или .\venv\Scripts\activate на Windows
   ```
3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
4. Скопируйте `.env.example` в `.env` и заполните данные:
   ```bash
   cp .env.example .env
   ```
5. Запустите бота:
   ```bash
   python invest_bot.py
   ```

---

## 📄 Лицензия
MIT License. Проект создан в образовательных и персональных целях.
