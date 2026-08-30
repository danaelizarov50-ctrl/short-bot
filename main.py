import telebot
import requests
import re
import time
import io
import os
from threading import Thread
from flask import Flask

# --- ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖАНИЯ ОНЛАЙНА ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()

# --- НАСТРОЙКИ БОТА ---
BOT_TOKEN = "8986502114:AAFVjiRDeJYSJNRc2Hd7rBiCtjgG1-_sNDs"
API_KEY = "sk_aNOsM1BKzhp7H1q4"
DOMAIN = "gemini18monthgift.s.gy"

bot = telebot.TeleBot(BOT_TOKEN)

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": API_KEY,
}
endpoint = "https://api.short.io/links"

def shorten_single_url(url):
    payload = {"domain": DOMAIN, "originalURL": url}
    try:
        r = requests.post(endpoint, json=payload, headers=headers)
        if r.status_code in [200, 201]:
            return r.json().get("shortURL")
        return f"Ошибка: {r.json().get('message', 'Не удалось сократить')}"
    except Exception as e:
        return f"Исключение сети: {e}"

def process_and_shorten(urls_list):
    short_urls = []
    for url in urls_list:
        res = shorten_single_url(url)
        short_urls.append(res)
        time.sleep(0.1)
    return short_urls

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "👋 Привет!\nОтправь мне текст со ссылками или файл (.txt), и я верну готовые короткие ссылки.")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    file_name = message.document.file_name
    if not file_name.endswith(('.txt', '.csv', '.log')):
        bot.reply_to(message, "⚠️ Пожалуйста, отправьте текстовый файл формата `.txt`.")
        return

    status_msg = bot.reply_to(message, "📥 Обрабатываю файл...")
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        content = downloaded_file.decode('utf-8', errors='ignore')
        raw_urls = re.findall(r'(https?://[^\s\]\)]+)', content)

        if not raw_urls:
            bot.edit_message_text("❌ В файле не найдено ссылок.", chat_id=message.chat.id, message_id=status_msg.message_id)
            return

        bot.edit_message_text(f"⏳ Найдено ссылок: {len(raw_urls)}. Сокращаю...", chat_id=message.chat.id, message_id=status_msg.message_id)
        short_links = process_and_shorten(raw_urls)
        result_text = "\n".join(short_links)

        output_file = io.BytesIO(result_text.encode('utf-8'))
        output_file.name = "shortened_urls.txt"

        bot.send_document(chat_id=message.chat.id, document=output_file, caption=f"✅ Готово! Обработано: {len(short_links)} ссылок.")
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", chat_id=message.chat.id, message_id=status_msg.message_id)

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    raw_urls = re.findall(r'(https?://[^\s\]\)]+)', message.text)
    if not raw_urls:
        bot.reply_to(message, "❌ Не найдено ссылок.")
        return

    status_msg = bot.reply_to(message, f"⏳ Сокращаю ссылок: {len(raw_urls)}...")
    short_urls = process_and_shorten(raw_urls)
    result_text = "\n".join(short_urls)

    if len(result_text) > 4000:
        for x in range(0, len(result_text), 4000):
            bot.send_message(message.chat.id, result_text[x:x+4000])
    else:
        bot.send_message(message.chat.id, result_text)

    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except:
        pass

if __name__ == "__main__":
    keep_alive()
    print("✅ Бот запущен онлайн!")
    bot.infinity_polling()
