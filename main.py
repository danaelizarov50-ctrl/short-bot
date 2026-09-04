import telebot
from telebot import types
import requests
import re
import time
import io
import os
import sqlite3
from threading import Thread
from flask import Flask

# --- ВЕБ-СЕРВЕР ДЛЯ РАБОТЫ 24/7 НА RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()

# --- КОНФИГУРАЦИЯ И ТОКЕНЫ ---
BOT_TOKEN = "8986502114:AAFVjiRDeJYSJNRc2Hd7rBiCtjgG1-_sNDs"
API_KEY = "sk_aNOsM1BKzhp7H1q4"
DOMAIN = "gemini18monthgift.s.gy"
ADMIN_ID = 6598036118
FREE_DAILY_LIMIT = 10
PRICE_USD = 0.60

# Платежные API ключи
CRYPTOBOT_TOKEN = "628354:AANzrpCtUYWERmgGnS0AJPwwIeWeUESleGO"
XROCKET_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHBJZCI6IjMwMDIzMCIsImp0aSI6ImFwcDozMDAyMzA6MzU1NDdmNmEtZjk0My00MDZlLTg0NzEtNWJjYTZkOWJlMjU1IiwiaWF0IjoxNzg4MDkwODAwfQ.52SDkwaYn9t1Wz54duZ6ACdoZJpg3dwf60tv95lfG2k"

# Реквизиты СБП и криптокошельков
SBP_DETAILS = "+7 (999) 000-00-00 (Тинькофф / Сбер)"
CRYPTO_WALLETS = "• USDT (TRC-20): `TXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`\n• TON: `UQXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`"

bot = telebot.TeleBot(BOT_TOKEN)

# --- ИЗОЛИРОВАННАЯ РАБОТА С БД ---
def get_db():
    conn = sqlite3.connect("database.db", timeout=10)
    return conn

with get_db() as conn:
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        is_vip INTEGER DEFAULT 0,
        daily_used INTEGER DEFAULT 0,
        last_reset_date TEXT
    )
    """)
    conn.commit()

def get_user_status(user_id):
    if user_id == ADMIN_ID:
        return {"is_vip": 1, "daily_used": 0}
    
    today = time.strftime("%Y-%m-%d")
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT is_vip, daily_used, last_reset_date FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        if not row:
            c.execute("INSERT INTO users (user_id, is_vip, daily_used, last_reset_date) VALUES (?, 0, 0, ?)", (user_id, today))
            conn.commit()
            return {"is_vip": 0, "daily_used": 0}
        
        is_vip, daily_used, last_date = row
        if last_date != today:
            c.execute("UPDATE users SET daily_used = 0, last_reset_date = ? WHERE user_id = ?", (today, user_id))
            conn.commit()
            daily_used = 0
        return {"is_vip": is_vip, "daily_used": daily_used}

def set_vip_success(user_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (user_id,))
        conn.commit()

def increment_usage(user_id, count):
    if user_id != ADMIN_ID:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET daily_used = daily_used + ? WHERE user_id = ?", (count, user_id))
            conn.commit()

# --- СЕРВИС SHORT.IO ---
shortio_headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": API_KEY,
}

def shorten_single_url(url):
    payload = {"domain": DOMAIN, "originalURL": url}
    try:
        r = requests.post("https://api.short.io/links", json=payload, headers=shortio_headers, timeout=10)
        if r.status_code in [200, 201]:
            return r.json().get("shortURL")
        return f"Ошибка: {r.json().get('message', 'Сбой')}"
    except Exception as e:
        return "Ошибка сети"

def process_and_shorten(urls_list):
    short_urls = []
    for url in urls_list:
        res = shorten_single_url(url)
        short_urls.append(res)
        time.sleep(0.05)
    return short_urls

# --- ШЛЮЗ CRYPTOBOT API ---
def create_cryptobot_invoice(amount, user_id):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    payload = {
        "asset": "USDT",
        "amount": str(amount),
        "description": "Покупка вечного VIP доступа",
        "payload": str(user_id)
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10).json()
        if res.get("ok"):
            return res["result"]["invoice_id"], res["result"]["pay_url"]
    except:
        pass
    return None, None

def check_cryptobot_invoice(invoice_id):
    url = "https://pay.crypt.bot/api/getInvoices"
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}
    params = {"invoice_ids": str(invoice_id)}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10).json()
        if res.get("ok") and len(res["result"]["items"]) > 0:
            return res["result"]["items"][0]["status"] == "paid"
    except:
        pass
    return False

# --- ШЛЮЗ XROCKET API ---
def create_xrocket_invoice(amount, user_id):
    url = "https://pay.ton-rocket.com/tg-invoices"
    headers = {"Rocket-Pay-Key": XROCKET_API_KEY}
    payload = {
        "amount": float(amount),
        "currency": "USDT",
        "description": "Покупка вечного VIP доступа",
        "hidden_message": "Спасибо за покупку VIP!",
        "payload": str(user_id)
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10).json()
        if res.get("success"):
            return res["data"]["id"], res["data"]["link"]
    except:
        pass
    return None, None

def check_xrocket_invoice(invoice_id):
    url = f"https://pay.ton-rocket.com/tg-invoices/{invoice_id}"
    headers = {"Rocket-Pay-Key": XROCKET_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if res.get("success"):
            return res["data"]["status"] == "paid"
    except:
        pass
    return False

# --- ОСНОВНЫЕ КОМАНДЫ ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    u = get_user_status(message.from_user.id)
    status_text = "👑 Безлимит навсегда" if u["is_vip"] else f"Лимит: {u['daily_used']}/{FREE_DAILY_LIMIT} сегодня"
    bot.reply_to(
        message,
        f"👋 **Добро пожаловать в Shortener Bot!**\n\n"
        f"📊 **Ваш статус:** {status_text}\n\n"
        f"**Команды:**\n"
        f"• Отправьте список ссылок сообщением или `.txt` файлом\n"
        f"• `/buy` — купить вечный безлимит за ~0.60$\n"
        f"• `/status` — проверить текущий лимит",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['status'])
def send_status(message):
    u = get_user_status(message.from_user.id)
    status_text = "👑 Безлимит навсегда" if u["is_vip"] else f"Лимит: {u['daily_used']}/{FREE_DAILY_LIMIT} сегодня"
    bot.reply_to(message, f"📊 **Ваш статус:** {status_text}", parse_mode="Markdown")

@bot.message_handler(commands=['givevip'])
def cmd_give_vip(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target_id = int(message.text.split()[1])
        set_vip_success(target_id)
        bot.reply_to(message, f"✅ VIP успешно выдан пользователю `{target_id}`!")
        bot.send_message(target_id, "👑 Администратор активировал вам вечный VIP-доступ!")
    except:
        bot.reply_to(message, "Используйте: `/givevip USER_ID`", parse_mode="Markdown")

# --- МЕНЮ ОПЛАТЫ ---
@bot.message_handler(commands=['buy'])
def send_buy_menu(message):
    u = get_user_status(message.from_user.id)
    if u["is_vip"] and message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "👑 У вас уже активирован вечный VIP-доступ!")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🤖 Оплатить через CryptoBot ($0.60)", callback_data="buy_cryptobot"),
        types.InlineKeyboardButton("🚀 Оплатить через xRocket ($0.60)", callback_data="buy_xrocket"),
        types.InlineKeyboardButton("⭐ Telegram Stars (30 Stars)", callback_data="buy_stars"),
        types.InlineKeyboardButton("💳 СБП / Банковская карта (60₽)", callback_data="buy_sbp"),
        types.InlineKeyboardButton("💎 Прямой перевод Crypto (USDT/TON)", callback_data="buy_crypto_direct")
    )
    bot.send_message(message.chat.id, "💳 **Покупка вечного безлимита ($0.60)**\n\nВыберите способ оплаты:", reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_"))
def handle_buy_callbacks(call):
    user_id = call.from_user.id

    if call.data == "buy_cryptobot":
        inv_id, pay_url = create_cryptobot_invoice(PRICE_USD, user_id)
        if pay_url:
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(
                types.InlineKeyboardButton("💳 Оплатить в @CryptoBot", url=pay_url),
                types.InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"chk_cb_{inv_id}")
            )
            bot.send_message(call.message.chat.id, f"🧾 **Счет на оплату $0.60 (USDT)**\n\nНажмите кнопку ниже, перейдите в бота и оплатите счет. После завершения нажмите кнопку «Проверить оплату».", reply_markup=kb, parse_mode="Markdown")
        else:
            bot.send_message(call.message.chat.id, "❌ Не удалось создать счет CryptoBot. Попробуйте позже.")

    elif call.data == "buy_xrocket":
        inv_id, pay_url = create_xrocket_invoice(PRICE_USD, user_id)
        if pay_url:
            kb = types.InlineKeyboardMarkup(row_width=1)
            kb.add(
                types.InlineKeyboardButton("🚀 Оплатить в @xrocket", url=pay_url),
                types.InlineKeyboardButton("🔄 Проверить оплату", callback_data=f"chk_xr_{inv_id}")
            )
            bot.send_message(call.message.chat.id, f"🧾 **Счет xRocket Pay на $0.60**\n\nНажмите кнопку ниже для оплаты в @xrocket. После оплаты нажмите «Проверить оплату».", reply_markup=kb, parse_mode="Markdown")
        else:
            bot.send_message(call.message.chat.id, "❌ Не удалось создать счет xRocket. Попробуйте позже.")

    elif call.data == "buy_stars":
        prices = [types.LabeledPrice(label="Вечный безлимит", amount=30)]
        bot.send_invoice(
            chat_id=call.message.chat.id,
            title="👑 VIP-доступ Навсегда",
            description="Безлимитное сокращение ссылок и файлов без ограничений.",
            invoice_payload="buy_lifetime_vip",
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter="buy_vip"
        )

    elif call.data == "buy_sbp":
        bot.send_message(call.message.chat.id, f"💳 **Оплата через СБП / Карту (60 руб)**\n\nРеквизиты:\n`{SBP_DETAILS}`\n\nПосле оплаты отправьте квитанцию администратору для активации доступа.", parse_mode="Markdown")

    elif call.data == "buy_crypto_direct":
        bot.send_message(call.message.chat.id, f"💎 **Прямой перевод Crypto ($0.60)**\n\n{CRYPTO_WALLETS}\n\nПосле отправки напишите администратору с TXID транзакции.", parse_mode="Markdown")

    bot.answer_callback_query(call.id)

# --- ПРОВЕРКА ОПЛАТЫ CRYPTOBOT / XROCKET ---
@bot.callback_query_handler(func=lambda c: c.data.startswith("chk_"))
def handle_check_payment(call):
    parts = call.data.split("_")
    gateway = parts[1]
    inv_id = parts[2]

    is_paid = False
    if gateway == "cb":
        is_paid = check_cryptobot_invoice(inv_id)
    elif gateway == "xr":
        is_paid = check_xrocket_invoice(inv_id)

    if is_paid:
        set_vip_success(call.from_user.id)
        bot.answer_callback_query(call.id, "🎉 Оплата подтверждена!")
        bot.send_message(call.message.chat.id, "🎉 **Оплата успешно завершена!**\nВам активирован статус «👑 Безлимит навсегда».", parse_mode="Markdown")
    else:
        bot.answer_callback_query(call.id, "⏳ Оплата еще не поступила. Попробуйте через пару секунд.", show_alert=True)

# --- ПРОВЕРКА ОПЛАТЫ TELEGRAM STARS ---
@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def process_stars_payment(message):
    set_vip_success(message.from_user.id)
    bot.send_message(message.chat.id, "🎉 **Оплата принята!**\nВам активирован вечный VIP доступ.", parse_mode="Markdown")

# --- ОБРАБОТКА ФАЙЛОВ (.TXT) ---
@bot.message_handler(content_types=['document'])
def handle_document(message):
    file_name = message.document.file_name
    if not file_name.endswith(('.txt', '.csv', '.log')):
        bot.reply_to(message, "⚠️ Пожалуйста, отправьте текстовый файл формата `.txt`.")
        return

    u = get_user_status(message.from_user.id)

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        content = downloaded_file.decode('utf-8', errors='ignore')
        raw_urls = re.findall(r'(https?://[^\s\]\)]+)', content)

        if not raw_urls:
            bot.reply_to(message, "❌ В файле не найдено ссылок.")
            return

        if not u["is_vip"] and (u["daily_used"] + len(raw_urls)) > FREE_DAILY_LIMIT:
            bot.reply_to(message, f"❌ Превышен лимит. В файле {len(raw_urls)} ссылок, а доступно {FREE_DAILY_LIMIT - u['daily_used']}.\nКупите безлимит за 0.60$: `/buy`", parse_mode="Markdown")
            return

        status_msg = bot.reply_to(message, f"⏳ Найдено {len(raw_urls)} ссылок. Обрабатываю...")

        short_links = process_and_shorten(raw_urls)
        increment_usage(message.from_user.id, len(raw_urls))

        result_text = "\n".join(short_links)
        output_file = io.BytesIO(result_text.encode('utf-8'))
        output_file.name = "shortened_urls.txt"

        bot.send_document(
            chat_id=message.chat.id,
            document=output_file,
            caption=f"✅ Готово! Успешно сокращено: {len(short_links)} ссылок."
        )
        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при обработке: {e}")

# --- ОБРАБОТКА ОБЫЧНЫХ СООБЩЕНИЙ ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    raw_urls = re.findall(r'(https?://[^\s\]\)]+)', message.text)
    if not raw_urls:
        bot.reply_to(message, "❌ Отправьте ссылку или `.txt` файл.")
        return

    u = get_user_status(message.from_user.id)
    if not u["is_vip"] and (u["daily_used"] + len(raw_urls)) > FREE_DAILY_LIMIT:
        bot.reply_to(message, f"❌ Превышен дневной лимит ({u['daily_used']}/{FREE_DAILY_LIMIT}).\nКупите вечный безлимит за 0.60$: `/buy`", parse_mode="Markdown")
        return

    status_msg = bot.reply_to(message, f"⏳ Сокращаю ({len(raw_urls)} шт.)...")
    short_urls = process_and_shorten(raw_urls)
    increment_usage(message.from_user.id, len(raw_urls))

    result_text = "\n".join(short_urls)
    if len(result_text) > 4000:
        output_file = io.BytesIO(result_text.encode('utf-8'))
        output_file.name = "shortened_urls.txt"
        bot.send_document(message.chat.id, output_file, caption="✅ Ваши ссылки готовы!")
    else:
        bot.send_message(message.chat.id, result_text)

    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except:
        pass

if __name__ == "__main__":
    keep_alive()
    print("✅ Бот запущен с активными платежными шлюзами!")
    bot.infinity_polling()


@bot.message_handler(commands=['givevip'])
def cmd_give_vip(message):
    # Проверяем, что команду пишет именно админ (ты)
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Используй формат:\n`/givevip 123456789` (где число — Telegram ID пользователя)", parse_mode="Markdown")
        return

    try:
        target_id = int(parts[1].strip())
        
        # Записываем VIP в базу данных
        with get_db() as conn:
            c = conn.cursor()
            # Обновляем или добавляем пользователя с VIP-статусом
            c.execute("""
                INSERT INTO users (user_id, is_vip, daily_used, last_reset_date)
                VALUES (?, 1, 0, date('now'))
                ON CONFLICT(user_id) DO UPDATE SET is_vip = 1
            """, (target_id,))
            conn.commit()

        bot.reply_to(message, f"✅ VIP успешно выдан пользователю `{target_id}`!", parse_mode="Markdown")

        # Оповещаем пользователя, если он уже запускал бота
        try:
            bot.send_message(target_id, "👑 **Вам выдан постоянный VIP-доступ!**\nТеперь у вас безлимитное сокращение ссылок.", parse_mode="Markdown")
        except:
            pass

    except ValueError:
        bot.reply_to(message, "❌ Неверный ID. ID должен состоять только из цифр.")
