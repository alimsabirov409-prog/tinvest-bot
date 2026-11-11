import asyncio
import logging
import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import timedelta
from typing import Any, Awaitable, Callable, Dict
import aiohttp
from dotenv import load_dotenv, set_key
from t_tech.invest import AsyncClient, InstrumentIdType
from t_tech.invest.utils import now
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery, TelegramObject
from cryptography.fernet import Fernet

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = str(os.getenv("ADMIN_ID", "2126534573")).split()[0].strip().replace('"', '').replace("'", "")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    set_key(".env", "ENCRYPTION_KEY", ENCRYPTION_KEY)
    os.environ["ENCRYPTION_KEY"] = ENCRYPTION_KEY

cipher = Fernet(ENCRYPTION_KEY.encode())
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.getenv("DB_PATH", os.path.join(BASE_DIR, "users.db"))
USD_FIGI = "BBG0013HGFT4"
CNY_FIGI = "BBG0013HRTL0"

# ================= MIDDLEWARE (АНТИФЛУД) =================
class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, limit_sec: int = 3):
        self.limit = limit_sec
        self.cache = {}
        super().__init__()

    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: Dict[str, Any]) -> Any:
        if not isinstance(event, Message) or not event.text:
            return await handler(event, data)
        if event.text.startswith(('/report', '/upcoming', '/balance', '/rates')):
            user_id = event.from_user.id
            current_time = asyncio.get_event_loop().time()
            if user_id in self.cache and current_time - self.cache[user_id] < self.limit:
                await event.answer("⏱ **Не спамьте командами.** Подождите пару секунд.")
                return
            self.cache[user_id] = current_time
        return await handler(event, data)

dp.message.middleware(AntiFloodMiddleware(limit_sec=3))

# ================= БАЗА ДАННЫХ =================
def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_FILE)), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS users (chat_id TEXT PRIMARY KEY, tinkoff_token_encrypted TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    cursor.execute('CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, action TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit()
    conn.close()

def log_action(chat_id: str, action: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO activity_logs (chat_id, action) VALUES (?, ?)", (str(chat_id), action))
        conn.commit()
        conn.close()
    except Exception: pass

def get_user_token(chat_id: str) -> str:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT tinkoff_token_encrypted FROM users WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    return cipher.decrypt(row[0].encode()).decode() if row and row[0] else None

def save_user_token(chat_id: str, token: str):
    encrypted_token = cipher.encrypt(token.encode()).decode()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (chat_id, tinkoff_token_encrypted) VALUES (?, ?)', (chat_id, encrypted_token))
    conn.commit()
    conn.close()

def delete_user_data(chat_id: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

# ================= РАСЧЕТЫ И ЦБ РФ =================
async def fetch_cbr_eur_rate() -> float:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://www.cbr.ru/scripts/XML_daily.asp", timeout=5) as response:
                if response.status == 200:
                    xml_data = await response.text()
                    root = ET.fromstring(xml_data)
                    for valute in root.findall("Valute"):
                        if valute.find("CharCode").text == "EUR":
                            return float(valute.find("Value").text.replace(",", "."))
    except Exception: pass
    return 98.50

async def fetch_market_rates(client: AsyncClient) -> dict:
    rates = {"USD": 91.50, "EUR": 98.50, "CNY": 12.60}
    try:
        prices = await client.market_data.get_last_prices(figi=[USD_FIGI, CNY_FIGI])
        for p in prices.last_prices:
            val = float(p.price.units + p.price.nano / 1e9)
            if val > 0:
                if p.figi == USD_FIGI: rates["USD"] = val
                elif p.figi == CNY_FIGI: rates["CNY"] = val
    except Exception: pass
    rates["EUR"] = await fetch_cbr_eur_rate()
    return rates

async def fetch_portfolio_balance(token: str) -> dict:
    shares, bonds, etfs, cash = 0.0, 0.0, 0.0, 0.0
    async with AsyncClient(token) as client:
        rates = await fetch_market_rates(client)
        accounts_res = await client.users.get_accounts()
        active_accounts = [acc.id for acc in accounts_res.accounts if acc.status == 2]
        
        for acc_id in active_accounts:
            try:
                port = await client.operations.get_portfolio(account_id=acc_id)
                for pos in port.positions:
                    qty = float(pos.quantity.units + pos.quantity.nano / 1e9)
                    if qty <= 0: continue
                    
                    price = 0.0
                    if pos.current_price:
                        price = float(pos.current_price.units + pos.current_price.nano / 1e9)
                    elif pos.average_position_price:
                        price = float(pos.average_position_price.units + pos.average_position_price.nano / 1e9)
                    
                    nkd = 0.0
                    if pos.current_nkd:
                        nkd = float(pos.current_nkd.units + pos.current_nkd.nano / 1e9)

                    curr = pos.average_position_price.currency.lower() if pos.average_position_price and pos.average_position_price.currency else "rub"
                    currency_rate = 1.0
                    if "usd" in curr: currency_rate = rates["USD"]
                    elif "eur" in curr: currency_rate = rates["EUR"]
                    elif "cny" in curr: currency_rate = rates["CNY"]
                    
                    cost_in_rub = (price + nkd) * qty * currency_rate
                    
                    if pos.instrument_type == "share": shares += cost_in_rub
                    elif pos.instrument_type == "bond": bonds += cost_in_rub
                    elif pos.instrument_type == "etf": etfs += cost_in_rub
                    elif pos.instrument_type in ["currency", "cash"]: cash += cost_in_rub

                if port.total_amount_currencies:
                    cash_val = float(port.total_amount_currencies.units + port.total_amount_currencies.nano / 1e9)
                    if cash_val > 0 and cash == 0:
                        cash += cash_val
            except Exception as e:
                logging.error(f"Ошибка парсинга счета {acc_id}: {e}")

    total = shares + bonds + etfs + cash
    return {"total": total, "shares": shares, "bonds": bonds, "etf": etfs, "cash": cash}

async def fetch_invest_data(token: str, days_ahead: int) -> list:
    payments = []
    async with AsyncClient(token) as client:
        accounts_res = await client.users.get_accounts()
        active_accounts = [acc.id for acc in accounts_res.accounts if acc.status == 2]
        
        portfolio_dict = {}
        for acc_id in active_accounts:
            try:
                port = await client.operations.get_portfolio(account_id=acc_id)
                for pos in port.positions:
                    quantity = float(pos.quantity.units + pos.quantity.nano / 1e9)
                    if quantity > 0:
                        portfolio_dict[pos.figi] = portfolio_dict.get(pos.figi, 0) + quantity
            except: pass
        
        from_date = now()
        to_date = from_date + timedelta(days=days_ahead)
        
        for figi, quantity in portfolio_dict.items():
            try:
                inst_info = await client.instruments.get_instrument_by(id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI, class_code="", id=figi)
                asset_name = inst_info.instrument.name
                inst_type = inst_info.instrument.instrument_type
            except:
                asset_name, inst_type = "Неизвестный актив", ""

            if inst_type == 'bond' or figi.startswith("BBG"):
                try:
                    coupons = await client.instruments.get_bond_coupons(figi=figi, from_=from_date, to=to_date)
                    for c in coupons.events:
                        amount = float(c.pay_one_bond.units + c.pay_one_bond.nano / 1e9) * quantity
                        if amount > 0: payments.append({'name': asset_name, 'amount': amount, 'date': c.coupon_date, 'type': 'Купон'})
                except: pass
            try:
                divs = await client.instruments.get_dividends(figi=figi, from_=from_date, to=to_date)
                for d in divs.dividends:
                    amount = float(d.dividend_net.units + d.dividend_net.nano / 1e9) * quantity
                    if amount > 0: payments.append({'name': asset_name, 'amount': amount, 'date': d.payment_date, 'type': 'Дивиденды'})
            except: pass
    return payments


# ================= ХЭНДЛЕРЫ КОМАНД =================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    log_action(message.chat.id, "/start")
    if not get_user_token(str(message.chat.id)):
        welcome_text = (
            "👋 **Привет!**\n\n"
            "Это простой бот-помощник для мониторинга твоего портфеля в Т-Инвестициях. "
            "Он умеет собирать чистую статистику по активам и выплатам без захода в банковское приложение.\n\n"
            "**Что умеет бот:**\n"
            "📊 /balance — считает реальную стоимость активов (акции, облигации, фонды, кэш).\n"
            "🗓 /upcoming — показывает календарь выплат дивидендов и купонов на 30 дней.\n"
            "📈 /report — строит подробный прогноз поступлений на год (365 дней) вперед.\n"
            "💵 /rates — выдает актуальные курсы валют.\n\n"
            "🔒 **Про безопасность:** Бот работает через официальный API. Нужен токен с правами **«Только для чтения»**. Торговать или выводить деньги через него физически невозможно.\n\n"
            "Чтобы запустить бота, создай Read-Only токен в личном кабинете Т-Инвестиций и **отправь его сюда текстовым сообщением**."
        )
        await message.answer(welcome_text, parse_mode="Markdown")
    else:
        menu_text = (
            "📈 **Меню команд:**\n\n"
            "🔹 /balance — Стоимость портфеля и распределение\n"
            "🔹 /upcoming — Выплаты на ближайшие 30 дней\n"
            "🔹 /report — Прогноз выплат на 365 дней\n"
            "🔹 /rates — Курсы валют (Мосбиржа и ЦБ)\n\n"
            "⭐️ /donate — Поддержать автора (оплата сервера)\n"
            "❌ /logout — Удалить токен и выйти"
        )
        await message.answer(menu_text, parse_mode="Markdown")

@dp.message(Command("logout"))
async def cmd_logout(message: Message):
    log_action(message.chat.id, "/logout")
    delete_user_data(str(message.chat.id))
    await message.answer("Токен удален.")

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    log_action(message.chat.id, "/balance")
    token = get_user_token(str(message.chat.id))
    if not token: return await message.answer("Сначала отправьте токен.")
    await message.answer("💰 Рассчитываю рыночную стоимость портфеля... ⏳")
    try:
        data = await fetch_portfolio_balance(token)
        text = f"💰 **Общая стоимость активов:**\n🔥 **{data['total']:.2f} руб.**\n\n📊 **Распределение:**\n• 📈 Акции: {data['shares']:.2f} руб.\n• 📜 Облигации: {data['bonds']:.2f} руб.\n• 📦 Фонды (ETF): {data['etf']:.2f} руб.\n• 💵 Кэш: {data['cash']:.2f} руб."
        await message.answer(text, parse_mode="Markdown")
    except Exception: await message.answer("❌ Ошибка при расчете баланса.")

@dp.message(Command("rates"))
async def cmd_rates(message: Message):
    log_action(message.chat.id, "/rates")
    token = get_user_token(str(message.chat.id)) or get_user_token(str(ADMIN_ID))
    if not token: return
    try:
        async with AsyncClient(token) as client: rates = await fetch_market_rates(client)
        text = f"📈 **Курсы валют:**\n\n🇺🇸 USD: **{rates['USD']:.2f} руб.**\n🇪🇺 EUR: **{rates['EUR']:.2f} руб.** _(ЦБ РФ)_\n🇨🇳 CNY: **{rates['CNY']:.2f} руб.**"
        await message.answer(text, parse_mode="Markdown")
    except Exception: await message.answer("❌ Ошибка котировок.")

@dp.message(Command("upcoming"))
async def cmd_upcoming(message: Message):
    log_action(message.chat.id, "/upcoming")
    token = get_user_token(str(message.chat.id))
    if not token: return
    await message.answer("🔍 Ищу поступления (30 дней)... ⏳")
    try:
        payments = await fetch_invest_data(token, 30)
        if not payments: return await message.answer("В ближайшие 30 дней выплат нет.")
        payments.sort(key=lambda x: x['date'])
        text = f"🗓 **Ближайшие выплаты:**\n\n"
        for p in payments: text += f"📍 **{p['date'].strftime('%d.%m.%Y')}** | {p['name']}\n   +{p['amount']:.2f} руб. ({p['type']})\n\n"
        text += f"💰 **Суммарно:** {sum(p['amount'] for p in payments):.2f} руб."
        await message.answer(text, parse_mode="Markdown")
    except: await message.answer("❌ Ошибка данных.")

@dp.message(Command("report"))
async def cmd_report(message: Message):
    log_action(message.chat.id, "/report")
    token = get_user_token(str(message.chat.id))
    if not token: return
    await message.answer("📊 Анализирую портфель (365 дней)... ⏳")
    try:
        payments = await fetch_invest_data(token, 365)
        if not payments: return await message.answer("Выплат нет.")
        breakdown = {}
        for p in payments: breakdown[p['name']] = breakdown.get(p['name'], 0) + p['amount']
        text = f"📊 **Прогноз (365 дней):**\n\n🔥 **Итого:** {sum(p['amount'] for p in payments):.2f} руб.\n\n📑 **Топ-25:**\n"
        for name, amount in sorted(breakdown.items(), key=lambda x: x[1], reverse=True)[:25]: text += f"• {name}: {amount:.2f} руб.\n"
        await message.answer(text, parse_mode="Markdown")
    except: await message.answer("❌ Ошибка отчета.")

@dp.message(Command("donate"))
async def cmd_donate(message: Message):
    log_action(message.chat.id, "/donate")
    await message.answer_invoice(title="Поддержка ⭐️", description="Донат на сервер.", payload="stars", provider_token="", currency="XTR", prices=[LabeledPrice(label="Донат", amount=50)])

@dp.pre_checkout_query()
async def process_pre_checkout_query(pcq: PreCheckoutQuery): await pcq.answer(ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(msg: Message): await msg.answer("❤️ **Спасибо!**")

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if str(message.chat.id).strip() != ADMIN_ID:
        return
        
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT chat_id) FROM activity_logs WHERE timestamp >= date('now')")
        dau = cursor.fetchone()[0]
        cursor.execute("SELECT action, COUNT(*) FROM activity_logs GROUP BY action ORDER BY COUNT(*) DESC LIMIT 5")
        top = cursor.fetchall()
        conn.close()
        text = f"📊 **Админка:**\n\n👥 Юзеров в базе: **{total}**\n🔥 Активность за сегодня: **{dau}**\n\n📈 **Топ команд:**\n"
        for a, c in top: text += f"• `{a}`: {c} раз\n"
        await message.answer(text, parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка загрузки админки: {e}")

@dp.message(F.text.regexp(r'^[A-Za-z0-9_\-\.]{20,200}$'))
async def handle_token(message: Message):
    token = message.text.strip()
    await message.answer("🔄 Проверка токена...")
    try:
        async with AsyncClient(token) as client: await client.users.get_accounts()
        save_user_token(str(message.chat.id), token)
        await message.answer("✅ **Токен сохранен!** Нажмите /start для вызова меню.")
    except: await message.answer("❌ Ошибка валидации.")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())