import telebot
from telebot import types
import requests
from requests.adapters import HTTPAdapter
import re
import time
import io
import os
import sqlite3
import qrcode
from concurrent.futures import ThreadPoolExecutor, as_completed
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
FREE_DAILY_LIMIT = 10
ADMIN_ID = 6598036118

CRYPTOBOT_PAY_URL = "https://t.me/CryptoBot?start=pay"
XROCKET_PAY_URL = "https://t.me/xrocket?start=pay"
SBP_DETAILS = "+7 (999) 000-00-00 (Тинькофф / Сбер)"
CRYPTO_WALLETS = "• USDT (TRC-20): `TXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`\n• TON: `UQXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`"

bot = telebot.TeleBot(BOT_TOKEN)

# --- НАСТРОЙКА БАЗЫ ДАННЫХ ---
db = sqlite3.connect("database.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    lang TEXT DEFAULT 'ru',
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

# --- ТЕКСТЫ И ЛОКАЛИЗАЦИЯ ---
TEXTS = {
    'ru': {
        'start': "👋 **Добро пожаловать в Shortener Bot!**\n\n📊 Статус: {status}\n\n**Команды:**\n• Отправьте ссылку, список или `.txt` файл\n• `/custom <ссылка> <хвост>` — создать именную ссылку\n• `/stats <короткая_ссылка>` — статистика кликов\n• `/history` — история ваших ссылок\n• `/language` — сменить язык\n• `/buy` — купить вечный безлимит за ~0.60$",
        'vip_status': "👑 Безлимит навсегда",
        'free_status': "Лимит: {used}/{limit} ссылок сегодня",
        'select_lang': "🌐 Пожалуйста, выберите язык / Please select your language:",
        'limit_reached': "❌ Превышен лимит ({used}/{limit} сегодня).\nКупите безлимит навсегда за 0.60$: `/buy`",
        'choose_pay': "💳 **Покупка вечного безлимита (~$0.60 / 60₽)**\n\nВыберите удобный способ оплаты:",
        'pay_stars': "⭐ Telegram Stars (30 Stars)",
        'pay_crypto': "🤖 CryptoBot (USDT / TON)",
        'pay_xrocket': "🚀 xRocket",
        'pay_sbp': "🇷🇺 СБП / Банковская карта",
        'pay_direct_crypto': "💎 Прямой перевод Crypto (USDT/TON)",
        'sbp_info': f"💳 **Оплата через СБП / Карту (60 руб)**\n\nРеквизиты для перевода:\n`{SBP_DETAILS}`\n\nПосле оплаты отправьте чек администратору для активации.",
        'direct_crypto_info': f"💎 **Оплата криптовалютой ($0.60)**\n\n{CRYPTO_WALLETS}\n\nПосле отправки напишите админу с TXID транзакции.",
        'ready_one': "✅ Готово:",
        'bulk_start': "🚀 Начинаю обработку...",
        'bulk_done': "✅ Готово! Обработано {count} ссылок."
    },
    'en': {
        'start': "👋 **Welcome to Shortener Bot!**\n\n📊 Status: {status}\n\n**Commands:**\n• Send link(s) or `.txt` file\n• `/custom <link> <slug>` — create branded link\n• `/stats <short_link>` — view click stats\n• `/history` — recent links\n• `/language` — change language\n• `/buy` — lifetime unlimited for ~$0.60",
        'vip_status': "👑 Lifetime Unlimited",
        'free_status': "Limit: {used}/{limit} links today",
        'select_lang': "🌐 Please select your language / Пожалуйста, выберите язык:",
        'limit_reached': "❌ Daily limit exceeded ({used}/{limit} today).\nUnlock lifetime access for $0.60: `/buy`",
        'choose_pay': "💳 **Lifetime Unlimited Access (~$0.60)**\n\nSelect a payment method:",
        'pay_stars': "⭐ Telegram Stars (30 Stars)",
        'pay_crypto': "🤖 CryptoBot (USDT / TON)",
        'pay_xrocket': "🚀 xRocket",
        'pay_sbp': "🇷🇺 Card / SBP (RUB)",
        'pay_direct_crypto': "💎 Direct Crypto (USDT/TON)",
        'sbp_info': f"💳 **Payment via Card / SBP (60 RUB)**\n\nDetails:\n`{SBP_DETAILS}`\n\nAfter payment, send receipt to admin for activation.",
        'direct_crypto_info': f"💎 **Direct Crypto ($0.60)**\n\n{CRYPTO_WALLETS}\n\nAfter transaction, contact admin with TXID.",
        'ready_one': "✅ Ready:",
        'bulk_start': "🚀 Starting processing...",
        'bulk_done': "✅ Done! Processed {count} links."
    }
}

# --- ПОЛЬЗОВАТЕЛИ ---
def get_user(user_id):
    if user_id == ADMIN_ID:
        return {"lang": "ru", "is_vip": 1, "daily_used": 0, "new": False}

    today = time.strftime("%Y-%m-%d")
    cursor.execute("SELECT lang, is_vip, daily_used, last_reset_date FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, lang, is_vip, daily_used, last_reset_date) VALUES (?, 'ru', 0, 0, ?)", (user_id, today))
        db.commit()
        return {"lang": "ru", "is_vip": 0, "daily_used": 0, "new": True}
    
    lang, is_vip, daily_used, last_date = row
    if last_date != today:
        cursor.execute("UPDATE users SET daily_used = 0, last_reset_date = ? WHERE user_id = ?", (today, user_id))
        db.commit()
        daily_used = 0
    return {"lang": lang, "is_vip": is_vip, "daily_used": daily_used, "new": False}

def set_user_lang(user_id, lang):
    cursor.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))
    db.commit()

def add_usage(user_id, count):
    if user_id != ADMIN_ID:
        cursor.execute("UPDATE users SET daily_used = daily_used + ? WHERE user_id = ?", (count, user_id))
        db.commit()

# --- СЕССИЯ SHORT.IO С ПУЛОМ СОЕДИНЕНИЙ ---
session = requests.Session()
adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=2)
session.mount('https://', adapter)
session.headers.update({
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": API_KEY,
})

def shorten_api(url, custom_slug=None):
    payload = {"domain": DOMAIN, "originalURL": url}
    if custom_slug:
        payload["path"] = custom_slug
    try:
        r = session.post("https://api.short.io/links", json=payload, timeout=8)
        if r.status_code in [200, 201]:
            return r.json().get("shortURL", url)
        # Если превышен рейт-лимит — делаем паузу и пробуем ещё раз
        if r.status_code == 429:
            time.sleep(0.5)
            r = session.post("https://api.short.io/links", json=payload, timeout=8)
            if r.status_code in [200, 201]:
                return r.json().get("shortURL", url)
        return f"Error_{r.status_code}"
    except Exception:
        return "Network_Error"

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

# --- КОМАНДЫ ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    u = get_user(message.from_user.id)
    if u.get("new"):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang_ru"),
               types.InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"))
        bot.send_message(message.chat.id, TEXTS['ru']['select_lang'], reply_markup=kb)
        return

    show_main_menu(message.chat.id, u)

@bot.message_handler(commands=['language'])
def cmd_language(message):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang_ru"),
           types.InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"))
    bot.send_message(message.chat.id, "🌐 Выберите язык / Select language:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("setlang_"))
def callback_set_lang(call):
    lang = call.data.split("_")[1]
    set_user_lang(call.from_user.id, lang)
    bot.answer_callback_query(call.id, "Язык сохранен / Language saved!")
    u = get_user(call.from_user.id)
    show_main_menu(call.message.chat.id, u)

def show_main_menu(chat_id, user_dict):
    l = user_dict["lang"]
    t = TEXTS[l]
    status = t['vip_status'] if user_dict['is_vip'] else t['free_status'].format(used=user_dict['daily_used'], limit=FREE_DAILY_LIMIT)
    bot.send_message(chat_id, t['start'].format(status=status), parse_mode="Markdown")

@bot.message_handler(commands=['buy'])
def cmd_buy(message):
    u = get_user(message.from_user.id)
    l = u["lang"]
    t = TEXTS[l]

    if u["is_vip"] and message.from_user.id != ADMIN_ID:
        bot.reply_to(message, t['vip_status'])
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(t['pay_stars'], callback_data="pay_stars"),
        types.InlineKeyboardButton(t['pay_crypto'], url=CRYPTOBOT_PAY_URL),
        types.InlineKeyboardButton(t['pay_xrocket'], url=XROCKET_PAY_URL),
        types.InlineKeyboardButton(t['pay_sbp'], callback_data="pay_sbp"),
        types.InlineKeyboardButton(t['pay_direct_crypto'], callback_data="pay_direct_crypto")
    )
    bot.send_message(message.chat.id, t['choose_pay'], parse_mode="Markdown", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("pay_"))
def callback_payment(call):
    u = get_user(call.from_user.id)
    l = u["lang"]
    t = TEXTS[l]

    if call.data == "pay_stars":
        prices = [types.LabeledPrice(label="Lifetime VIP", amount=30)]
        bot.send_invoice(
            chat_id=call.message.chat.id,
            title="VIP Access",
            description="Lifetime unlimited link shortening & custom slugs.",
            invoice_payload="buy_lifetime_vip",
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter="buy_vip"
        )
    elif call.data == "pay_sbp":
        bot.send_message(call.message.chat.id, t['sbp_info'], parse_mode="Markdown")
    elif call.data == "pay_direct_crypto":
        bot.send_message(call.message.chat.id, t['direct_crypto_info'], parse_mode="Markdown")
    
    bot.answer_callback_query(call.id)

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def process_payment(message):
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (message.from_user.id,))
    db.commit()
    bot.send_message(message.chat.id, "🎉 **VIP Activated!**", parse_mode="Markdown")

@bot.message_handler(commands=['givevip'])
def cmd_give_vip(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target_id = int(message.text.split()[1])
        cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_id,))
        db.commit()
        bot.reply_to(message, f"✅ VIP успешно выдан пользователю `{target_id}`!")
        bot.send_message(target_id, "👑 Администратор активировал вам вечный VIP-доступ!")
    except:
        bot.reply_to(message, "Используйте: `/givevip USER_ID`", parse_mode="Markdown")

@bot.message_handler(commands=['custom'])
def cmd_custom(message):
    u = get_user(message.from_user.id)
    l = u["lang"]
    t = TEXTS[l]

    if not u["is_vip"] and u["daily_used"] >= FREE_DAILY_LIMIT:
        bot.reply_to(message, t['limit_reached'].format(used=u['daily_used'], limit=FREE_DAILY_LIMIT), parse_mode="Markdown")
        return

    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "Формат / Format:\n`/custom https://example.com my-slug`", parse_mode="Markdown")
        return

    res = shorten_api(parts[1], custom_slug=parts[2])
    if res.startswith("http"):
        add_usage(message.from_user.id, 1)
        qr = generate_qr(res)
        bot.send_photo(message.chat.id, qr, caption=f"{t['ready_one']} {res}")
    else:
        bot.reply_to(message, f"❌ {res}")

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Формат: `/stats https://gemini18monthgift.s.gy/xxxx`", parse_mode="Markdown")
        return
    path = parts[1].strip().split("/")[-1]
    try:
        info_resp = session.get(f"https://api.short.io/links/expand?domain={DOMAIN}&path={path}").json()
        link_id = info_resp.get("idString")
        if not link_id:
            bot.reply_to(message, "❌ Link not found.")
            return
        stat_resp = session.get(f"https://api.short.io/statistics/link/{link_id}?period=total").json()
        clicks = stat_resp.get("humanClicks", 0)
        bot.reply_to(message, f"📊 Clicks / Переходов: **{clicks}**", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['history'])
def cmd_history(message):
    cursor.execute("SELECT original_url, short_url FROM links_history WHERE user_id = ? ORDER BY id DESC LIMIT 5", (message.from_user.id,))
    rows = cursor.fetchall()
    if not rows:
        bot.reply_to(message, "История пуста / History is empty.")
        return
    text = "📜 **Recent Links / История:**\n\n" + "\n\n".join([f"• {orig[:30]}... → {short}" for orig, short in rows])
    bot.reply_to(message, text, parse_mode="Markdown")

# --- СТАБИЛЬНАЯ ПАКЕТНАЯ ОБРАБОТКА (БЕЗ ЗАВИСАНИЙ) ---
def process_bulk_safe(raw_urls, message_id, chat_id):
    total = len(raw_urls)
    results = [None] * total
    completed = 0
    last_edit = time.time()

    def worker(item):
        idx, url = item
        res = shorten_api(url)
        return idx, res

    # 6 параллельных потоков — идеальный баланс между скоростью и лимитами Short.io
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(worker, (i, u)): i for i, u in enumerate(raw_urls)}
        for future in as_completed(futures):
            try:
                idx, res = future.result()
                results[idx] = res
            except Exception:
                idx = futures[future]
                results[idx] = raw_urls[idx]
            
            completed += 1
            
            # Обновление прогресс-бара каждые 3 секунды
            if time.time() - last_edit > 3.0 or completed == total:
                percent = int((completed / total) * 100)
                filled = int((completed / total) * 10)
                bar = "█" * filled + "░" * (10 - filled)
                try:
                    bot.edit_message_text(f"⚡ `[{bar}]` {percent}%\n({completed}/{total})", chat_id=chat_id, message_id=message_id, parse_mode="Markdown")
                except:
                    pass
                last_edit = time.time()
                
    return results

# --- ОБРАБОТКА ФАЙЛОВ И СООБЩЕНИЙ ---
@bot.message_handler(content_types=['document'])
def handle_doc(message):
    u = get_user(message.from_user.id)
    t = TEXTS[u["lang"]]
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        content = downloaded.decode('utf-8', errors='ignore')
        urls = re.findall(r'(https?://[^\s\]\)]+)', content)

        if not urls:
            bot.reply_to(message, "❌ No links found.")
            return

        if not u["is_vip"] and (u["daily_used"] + len(urls)) > FREE_DAILY_LIMIT:
            bot.reply_to(message, t['limit_reached'].format(used=u['daily_used'], limit=FREE_DAILY_LIMIT), parse_mode="Markdown")
            return

        status_msg = bot.reply_to(message, t['bulk_start'])
        res = process_bulk_safe(urls, status_msg.message_id, message.chat.id)
        add_usage(message.from_user.id, len(urls))

        out = io.BytesIO("\n".join(res).encode('utf-8'))
        out.name = "shortened_urls.txt"
        bot.send_document(message.chat.id, out, caption=t['bulk_done'].format(count=len(urls)))
        
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except:
            pass
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(func=lambda message: True)
def handle_msg(message):
    urls = re.findall(r'(https?://[^\s\]\)]+)', message.text)
    if not urls:
        bot.reply_to(message, "❌ Отправьте ссылку или файл / Send link or file.")
        return

    u = get_user(message.from_user.id)
    t = TEXTS[u["lang"]]

    if not u["is_vip"] and (u["daily_used"] + len(urls)) > FREE_DAILY_LIMIT:
        bot.reply_to(message, t['limit_reached'].format(used=u['daily_used'], limit=FREE_DAILY_LIMIT), parse_mode="Markdown")
        return

    if len(urls) == 1:
        res = shorten_api(urls[0])
        if res.startswith("http"):
            add_usage(message.from_user.id, 1)
            qr = generate_qr(res)
            bot.send_photo(message.chat.id, qr, caption=f"{t['ready_one']} {res}")
        else:
            bot.reply_to(message, res)
        return

    status_msg = bot.reply_to(message, t['bulk_start'])
    res = process_bulk_safe(urls, status_msg.message_id, message.chat.id)
    add_usage(message.from_user.id, len(urls))

    result_text = "\n".join(res)
    if len(result_text) > 4000:
        out = io.BytesIO(result_text.encode('utf-8'))
        out.name = "shortened_urls.txt"
        bot.send_document(message.chat.id, out, caption=t['bulk_done'].format(count=len(urls)))
    else:
        bot.send_message(message.chat.id, result_text)
    
    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except:
        pass

if __name__ == "__main__":
    keep_alive()
    print("✅ Бот готов и стабильно работает!")
    bot.infinity_polling()
