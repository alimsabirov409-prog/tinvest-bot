#!/usr/bin/env bash
set -e

# ==========================================
# Конфигурация по умолчанию
# ==========================================
APP_DIR="/opt/tinvest_bot"
SERVICE_NAME="tinvestbot"
DEFAULT_REPO_URL="https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME.git"
REPO_URL="${REPO_URL:-$DEFAULT_REPO_URL}"

# Цвета для вывода в терминал
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}====================================================${NC}"
echo -e "${CYAN}        Развертывание T-Invest Telegram Bot         ${NC}"
echo -e "${CYAN}====================================================${NC}"

# 1. Проверка прав суперпользователя (root)
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Ошибка: Запусти скрипт с правами root (через sudo):${NC}"
  echo -e "${YELLOW}sudo bash $0${NC} или ${YELLOW}curl -sSL ... | sudo bash${NC}"
  exit 1
fi

# Функция безопасного чтения ввода даже при вызове через пайп (curl ... | bash)
read_input() {
    local prompt="$1"
    local var_name="$2"
    local input_val=""
    if [ -t 0 ]; then
        read -rp "$prompt" input_val
    elif [ -e /dev/tty ]; then
        read -rp "$prompt" input_val < /dev/tty
    else
        echo -e "${RED}Не удалось открыть TTY для ввода. Передайте параметры через переменные окружения: TELEGRAM_TOKEN и ADMIN_ID.${NC}"
        exit 1
    fi
    printf -v "$var_name" '%s' "$input_val"
}

# 2. Запрос параметров (если не заданы через env)
if [ -z "$TELEGRAM_TOKEN" ]; then
    read_input "Введи TELEGRAM_TOKEN от @BotFather: " TELEGRAM_TOKEN
fi

if [ -z "$ADMIN_ID" ]; then
    read_input "Введи свой числовой ADMIN_ID (узнать в @userinfobot): " ADMIN_ID
fi

if [ -z "$TELEGRAM_TOKEN" ] || [ -z "$ADMIN_ID" ]; then
    echo -e "${RED}Ошибка: TELEGRAM_TOKEN и ADMIN_ID обязательны для работы!${NC}"
    exit 1
fi

echo -e "\n${GREEN}[1/6] Обновление системных пакетов и установка зависимостей...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl

echo -e "${GREEN}[2/6] Подготовка директории приложения: ${APP_DIR}...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"

# Если скрипт запущен внутри папки с кодом проекта
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/invest_bot.py" ] && [ "$SCRIPT_DIR" != "$APP_DIR" ]; then
    echo "Копирование исходных файлов из текущей папки в $APP_DIR..."
    mkdir -p "$APP_DIR"
    cp -r "$SCRIPT_DIR"/* "$APP_DIR"/ 2>/dev/null || true
    cp "$SCRIPT_DIR"/.env* "$APP_DIR"/ 2>/dev/null || true
elif [ ! -f "$APP_DIR/invest_bot.py" ]; then
    # Если запущен через curl | bash на чистом сервере
    if [[ "$REPO_URL" == *"YOUR_GITHUB_USERNAME"* ]]; then
        echo -e "${YELLOW}Внимание: REPO_URL не настроен. Скачиваю файлы бота напрямую...${NC}"
    fi
    mkdir -p "$APP_DIR"
    if [ -n "$RAW_BASE_URL" ]; then
        curl -sSL "$RAW_BASE_URL/invest_bot.py" -o "$APP_DIR/invest_bot.py"
        curl -sSL "$RAW_BASE_URL/requirements.txt" -o "$APP_DIR/requirements.txt"
    else
        # Клонируем репозиторий во временную папку или сразу в целевую
        TMP_CLONE="/tmp/tinvest_clone_$$"
        rm -rf "$TMP_CLONE"
        if git clone --depth 1 "$REPO_URL" "$TMP_CLONE" 2>/dev/null; then
            cp -r "$TMP_CLONE"/* "$APP_DIR"/
            rm -rf "$TMP_CLONE"
        else
            echo -e "${YELLOW}Не удалось клонировать по git. Убедитесь, что репозиторий публичный или REPO_URL указан верно.${NC}"
        fi
    fi
fi

cd "$APP_DIR"

if [ ! -f "$APP_DIR/invest_bot.py" ]; then
    echo -e "${RED}Критическая ошибка: файл invest_bot.py не найден в $APP_DIR!${NC}"
    exit 1
fi

echo -e "${GREEN}[3/6] Настройка виртуального окружения Python...${NC}"
if [ ! -d "$APP_DIR/venv" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip setuptools wheel

echo -e "${GREEN}[4/6] Установка Python-зависимостей...${NC}"
if [ -f "$APP_DIR/requirements.txt" ]; then
    "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
else
    "$APP_DIR/venv/bin/pip" install --quiet git+https://github.com/T-Investments/invest-python.git aiogram>=3.0.0 aiohttp python-dotenv cryptography
fi

echo -e "${GREEN}[5/6] Генерация и сохранение конфигурации .env...${NC}"
# Генерируем Fernet ключ шифрования с помощью установленной cryptography
if [ -z "$ENCRYPTION_KEY" ]; then
    ENCRYPTION_KEY=$("$APP_DIR/venv/bin/python3" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
fi

cat <<EOF > "$APP_DIR/.env"
TELEGRAM_TOKEN="${TELEGRAM_TOKEN}"
ADMIN_ID="${ADMIN_ID}"
ENCRYPTION_KEY="${ENCRYPTION_KEY}"
EOF
chmod 600 "$APP_DIR/.env"

echo -e "${GREEN}[6/6] Регистрация и запуск systemd-службы ${SERVICE_NAME}...${NC}"
cat <<EOF > "/etc/systemd/system/${SERVICE_NAME}.service"
[Unit]
Description=T-Invest Multiuser Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/venv/bin/python3 ${APP_DIR}/invest_bot.py
Restart=always
RestartSec=5
EnvironmentFile=${APP_DIR}/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo -e "\n${CYAN}====================================================${NC}"
echo -e "${GREEN}🎉 Установка успешно завершена! Бот запущен.${NC}"
echo -e "${CYAN}====================================================${NC}"
echo -e "🔹 Проверить статус службы:  ${YELLOW}systemctl status ${SERVICE_NAME}${NC}"
echo -e "🔹 Смотреть логи работы:     ${YELLOW}journalctl -u ${SERVICE_NAME} -f${NC}"
echo -e "🔹 Перезапуск бота:          ${YELLOW}systemctl restart ${SERVICE_NAME}${NC}"
echo -e "🔹 Остановка бота:           ${YELLOW}systemctl stop ${SERVICE_NAME}${NC}"
echo -e "${CYAN}====================================================${NC}\n"
