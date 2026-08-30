import telebot
from telebot import types
import requests
import re
import time
import io
import os
import sqlite3
import qrcode
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from flask import Flask

# --- ВЕБ-СЕРВЕР ДЛЯ РАБОТЫ 24/7 ---
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

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8986502114:AAFVjiRDeJYSJNRc2Hd7rBiCtjgG1-_sNDs"
API_KEY = "sk_aNOsM1BKzhp7H1q4"
DOMAIN = "gemini18monthgift.s.gy"
FREE_DAILY_LIMIT = 5
PRICE_STARS = 30  # ~0.60 USD в Telegram Stars

bot = telebot.TeleBot(BOT_TOKEN)

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
db = sqlite3.connect("database.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    is_vip INTEGER DEFAULT 0,
    daily_used INTEGER DEFAULT 0,
    last_reset_date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS links_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    original_url TEXT,
    short_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
db.commit()

# --- СИСТЕМА ЛИМИТОВ И VIP ---
def get_user(user_id):
    today = time.strftime("%Y-%m-%d")
    cursor.execute("SELECT is_vip, daily_used, last_reset_date FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, is_vip, daily_used, last_reset_date) VALUES (?, 0, 0, ?)", (user_id, today))
        db.commit()
        return {"is_vip": 0, "daily_used": 0}
    
    is_vip, daily_used, last_date = row
    if last_date != today:
        cursor.execute("UPDATE users SET daily_used = 0, last_reset_date = ? WHERE user_id = ?", (today, user_id))
        db.commit()
        daily_used = 0
    return {"is_vip": is_vip, "daily_used": daily_used}

def add_usage(user_id, count):
    cursor.execute("UPDATE users SET daily_used = daily_used + ? WHERE user_id = ?", (count, user_id))
    db.commit()

def save_link_history(user_id, original, short):
    cursor.execute("INSERT INTO links_history (user_id, original_url, short_url) VALUES (?, ?, ?)", (user_id, original, short))
    db.commit()

# --- SHORT.IO API ---
headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": API_KEY,
}

def shorten_api(url, custom_slug=None):
    payload = {"domain": DOMAIN, "originalURL": url}
    if custom_slug:
        payload["path"] = custom_slug
    try:
        r = requests.post("https://api.short.io/links", json=payload, headers=headers, timeout=10)
        if r.status_code in [200, 201]:
            return r.json().get("shortURL")
        return f"Ошибка: {r.json().get('message', 'Не удалось')}"
    except Exception as e:
        return f"Сетевая ошибка"

def generate_qr(url_text):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    bio.name = 'qr.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio

# --- КОМАНДЫ БОТА ---
@bot.message_handler(commands=['start', 'help'])
def cmd_start(message):
    u = get_user(message.from_user.id)
    vip_status = "👑 Безлимит навсегда" if u["is_vip"] else f"Лимит: {u['daily_used']}/{FREE_DAILY_LIMIT} сегодня"
    text = (
        f"👋 **Универсальный сокращатель ссылок**\n\n"
        f"📊 **Ваш статус:** {vip_status}\n\n"
        f"**Доступные команды:**\n"
        f"• Просто отправьте ссылки или `.txt` файл для сокращения\n"
        f"• `/custom <ссылка> <хвост>` — создать именную ссылку\n"
        f"• `/stats <короткая_ссылка>` — статистика переходов\n"
        f"• `/history` — список ваших последних ссылок\n"
        f"• `/buy` — купить вечный безлимит за ~0.60$ (30 ⭐)"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

# Покупка вечного доступа
@bot.message_handler(commands=['buy'])
def cmd_buy(message):
    u = get_user(message.from_user.id)
    if u["is_vip"]:
        bot.reply_to(message, "👑 У вас уже активирован вечный безлимитный доступ!")
        return

    prices = [types.LabeledPrice(label="Вечный безлимит", amount=PRICE_STARS)]
    bot.send_invoice(
        chat_id=message.chat.id,
        title="👑 VIP-доступ Навсегда",
        description="Безлимитное сокращение любых объемов ссылок, статистика и кастомные ссылки без ограничений.",
        invoice_payload="buy_lifetime_vip",
        provider_token="",
        currency="XTR",
        prices=prices,
        start_parameter="buy_vip"
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def process_payment(message):
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (message.from_user.id,))
    db.commit()
    bot.send_message(message.chat.id, "🎉 **Оплата принята!**\nВам открыт постоянный безлимитный доступ ко всем функциям.", parse_mode="Markdown")

# Создание кастомной ссылки
@bot.message_handler(commands=['custom'])
def cmd_custom(message):
    u = get_user(message.from_user.id)
    if not u["is_vip"] and u["daily_used"] >= FREE_DAILY_LIMIT:
        bot.reply_to(message, "❌ Вы исчерпали дневной бесплатный лимит. Разблокируйте безлимит: `/buy`", parse_mode="Markdown")
        return

    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "Используйте формат:\n`/custom https://example.com/long мой-хвост`", parse_mode="Markdown")
        return

    url, slug = parts[1], parts[2]
    res = shorten_api(url, custom_slug=slug)
    if res.startswith("http"):
        add_usage(message.from_user.id, 1)
        save_link_history(message.from_user.id, url, res)
        qr = generate_qr(res)
        bot.send_photo(message.chat.id, qr, caption=f"✅ Готово: {res}")
    else:
        bot.reply_to(message, f"❌ {res}")

# Статистика кликов
@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Используйте формат: `/stats https://gemini18monthgift.s.gy/xxxx`", parse_mode="Markdown")
        return

    short_url = parts[1].strip()
    path = short_url.split("/")[-1]
    
    try:
        # Получаем Link ID
        info_resp = requests.get(f"https://api.short.io/links/expand?domain={DOMAIN}&path={path}", headers=headers).json()
        link_id = info_resp.get("idString")
        if not link_id:
            bot.reply_to(message, "❌ Ссылка не найдена в базе домена.")
            return

        # Запрашиваем статистику
        stat_resp = requests.get(f"https://api.short.io/statistics/link/{link_id}?period=total", headers=headers).json()
        total_clicks = stat_resp.get("humanClicks", 0)
        bot.reply_to(message, f"📊 **Статистика для {short_url}:**\n\n👆 Всего переходов (кликов): **{total_clicks}**", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка получения статистики: {e}")

# История ссылок
@bot.message_handler(commands=['history'])
def cmd_history(message):
    cursor.execute("SELECT original_url, short_url FROM links_history WHERE user_id = ? ORDER BY id DESC LIMIT 5", (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        bot.reply_to(message, "У вас пока нет сохраненной истории.")
        return
    text = "📜 **Последние сокращенные ссылки:**\n\n" + "\n\n".join([f"• {orig[:30]}... → {short}" for orig, short in rows])
    bot.reply_to(message, text, parse_mode="Markdown")

# --- МНОГОПОТОЧНАЯ ПАКЕТНАЯ ОБРАБОТКА (БЫСТРО + ПРОГРЕСС-БАР) ---
def process_bulk_fast(user_id, raw_urls, message_id, chat_id):
    total = len(raw_urls)
    results = [None] * total
    completed = 0
    last_edit = time.time()

    def worker(idx_url):
        idx, url = idx_url
        res = shorten_api(url)
        if res.startswith("http"):
            save_link_history(user_id, url, res)
        return idx, res

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, (i, u)) for i, u in enumerate(raw_urls)]
        for f in futures:
            idx, res = f.result()
            results[idx] = res
            completed += 1

            # Обновление прогресс-бара каждые 1.5 сек (защита от Telegram Rate Limits)
            if time.time() - last_edit > 1.5 or completed == total:
                percent = int((completed / total) * 100)
                filled = int((completed / total) * 10)
                bar = "█" * filled + "░" * (10 - filled)
                try:
                    bot.edit_message_text(
                        f"⚡ **Обработка ссылок:**\n`[{bar}]` {percent}%\nУспешно: {completed}/{total}",
                        chat_id=chat_id,
                        message_id=message_id,
                        parse_mode="Markdown"
                    )
                except:
                    pass
                last_edit = time.time()

    return results

# --- ОБРАБОТКА ФАЙЛОВ И ТЕКСТА ---
@bot.message_handler(content_types=['document'])
def handle_doc(message):
    u = get_user(message.from_user.id)
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        content = downloaded.decode('utf-8', errors='ignore')
        urls = re.findall(r'(https?://[^\s\]\)]+)', content)

        if not urls:
            bot.reply_to(message, "❌ Ссылок в файле не найдено.")
            return

        if not u["is_vip"] and (u["daily_used"] + len(urls)) > FREE_DAILY_LIMIT:
            bot.reply_to(message, f"❌ Превышен лимит. В файле {len(urls)} ссылок, а доступно {FREE_DAILY_LIMIT - u['daily_used']}.\nКупите безлимит навсегда за 30 ⭐: `/buy`", parse_mode="Markdown")
            return

        status_msg = bot.reply_to(message, "🚀 Запуск быстрой обработки...")
        res = process_bulk_fast(message.from_user.id, urls, status_msg.message_id, message.chat.id)
        add_usage(message.from_user.id, len(urls))

        out = io.BytesIO("\n".join(res).encode('utf-8'))
        out.name = "shortened_urls.txt"
        bot.send_document(message.chat.id, out, caption=f"✅ Обработано {len(urls)} ссылок.")
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.message_handler(func=lambda message: True)
def handle_msg(message):
    urls = re.findall(r'(https?://[^\s\]\)]+)', message.text)
    if not urls:
        bot.reply_to(message, "❌ Отправьте ссылку, список или файл.")
        return

    u = get_user(message.from_user.id)
    if not u["is_vip"] and (u["daily_used"] + len(urls)) > FREE_DAILY_LIMIT:
        bot.reply_to(message, f"❌ Превышен дневной лимит ({u['daily_used']}/{FREE_DAILY_LIMIT}).\nРазблокируйте вечный безлимит: `/buy`", parse_mode="Markdown")
        return

    # Если одна ссылка — выдаем сразу ссылку + QR-код
    if len(urls) == 1:
        res = shorten_api(urls[0])
        if res.startswith("http"):
            add_usage(message.from_user.id, 1)
            save_link_history(message.from_user.id, urls[0], res)
            qr = generate_qr(res)
            bot.send_photo(message.chat.id, qr, caption=f"🔗 {res}")
        else:
            bot.reply_to(message, res)
        return

    # Если пачка ссылок — запускаем многопоточную обработку
    status_msg = bot.reply_to(message, "🚀 Запуск быстрой обработки...")
    res = process_bulk_fast(message.from_user.id, urls, status_msg.message_id, message.chat.id)
    add_usage(message.from_user.id, len(urls))

    result_text = "\n".join(res)
    if len(result_text) > 4000:
        out = io.BytesIO(result_text.encode('utf-8'))
        out.name = "shortened_urls.txt"
        bot.send_document(message.chat.id, out, caption="✅ Ваши ссылки готовы!")
    else:
        bot.send_message(message.chat.id, result_text)
    
    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except:
        pass

if __name__ == "__main__":
    keep_alive()
    print("✅ Бот со всеми модулями запущен!")
    bot.infinity_polling()
