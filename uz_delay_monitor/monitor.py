import html
import json
import os
import re
import time
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
import requests

OPTIONS_FILE = "/data/options.json"
STATE_STORAGE = "/data/last_seen_id.txt"

if os.path.exists(OPTIONS_FILE):
    with open(OPTIONS_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
else:
    raise RuntimeError("Конфігураційний файл /data/options.json відсутній!")

CHANNEL_USERNAME = str(config.get("channel_username", "UZprymisky")).lstrip("@")
INTERVAL = int(config.get("check_interval_seconds", 30))
TG_BOT_TOKEN = config.get("tg_bot_token", "").strip()
TG_CHAT_IDS = config.get("tg_chat_ids", [])
TOPIC_PREFIX = config.get("mqtt_topic_prefix", "uz/train_delay").rstrip("/")

TRAIN_SCHEDULES = {
    str(item["train_id"]).strip(): str(item["schedule"]).strip()
    for item in config.get("train_schedules", [])
}

MQTT_TOPIC_STATE = f"{TOPIC_PREFIX}/state"
MQTT_TOPIC_ATTRS = f"{TOPIC_PREFIX}/attributes"

MQTT_BROKER = os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

sorted_keys = sorted(TRAIN_SCHEDULES.keys(), key=len, reverse=True)
TRAIN_PATTERN = (
    re.compile(r"(" + "|".join([re.escape(x) for x in sorted_keys]) + r")")
    if sorted_keys
    else None
)

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
if MQTT_USER and MQTT_PASSWORD:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

def on_connect(client, userdata, flags, rc, properties=None):
    print("MQTT: Підключено успішно.", flush=True)

mqtt_client.on_connect = on_connect
try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"MQTT помилка підключення: {e}", flush=True)

def load_last_id():
    if os.path.exists(STATE_STORAGE):
        try:
            with open(STATE_STORAGE, "r") as f:
                return int(f.read().strip())
        except Exception:
            return 0
    return 0

def save_last_id(msg_id):
    with open(STATE_STORAGE, "w") as f:
        f.write(str(msg_id))

def send_telegram(text):
    if not TG_BOT_TOKEN or not TG_CHAT_IDS:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    for chat_id in TG_CHAT_IDS:
        try:
            data = {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            print(f"Помилка відправки Telegram ({chat_id}): {e}", flush=True)

def format_line_with_schedule(line, train_id):
    schedule = TRAIN_SCHEDULES.get(train_id, "").strip()
    clean_line = line.replace("**", "").strip()

    pattern = re.compile(rf"(№?\s*{re.escape(train_id)})\s+", re.IGNORECASE)
    if pattern.search(clean_line):
        clean_line = pattern.sub(r"\1\n", clean_line, count=1)

    if schedule and "курсує" in clean_line:
        clean_line = clean_line.replace("курсує", f"\n{schedule}\nкурсує", 1)
    elif schedule:
        clean_line = f"{clean_line}\n{schedule}"

    return f"🚆 Укрзалізниця: Затримка\n{clean_line}"

def extract_train_lines(full_text):
    if not TRAIN_PATTERN:
        return None, None
    matched_lines = []
    matched_trains = []

    for raw_line in full_text.splitlines():
        line = raw_line.strip()
        match = TRAIN_PATTERN.search(line)
        if match:
            train_id = match.group(1)
            matched_trains.append(train_id)
            formatted_line = format_line_with_schedule(line, train_id)
            matched_lines.append(formatted_line)

    if matched_lines:
        trains_label = ", ".join(dict.fromkeys(matched_trains))
        clean_message = "\n".join(matched_lines)
        return trains_label, clean_message
    return None, None

def fetch_channel_messages():
    url = f"https://t.me/s/{CHANNEL_USERNAME}"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"Не вдалося отримати сторінку каналу (HTTP {resp.status_code})", flush=True)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    posts = soup.find_all("div", class_="tgme_widget_message")
    results = []

    for post in posts:
        post_id_attr = post.get("data-post")
        if not post_id_attr:
            continue
        msg_id = int(post_id_attr.split("/")[-1])

        text_block = post.find("div", class_="tgme_widget_message_text")
        if not text_block:
            continue

        for br in text_block.find_all("br"):
            br.replace_with("\n")
        plain_text = text_block.get_text()

        time_tag = post.find("time")
        date_str = time_tag.get("datetime") if time_tag else time.strftime("%Y-%m-%d %H:%M:%S")

        results.append({
            "id": msg_id,
            "text": plain_text,
            "date": date_str
        })
    return results

def main():
    print(f"Запуск UZ Monitor для каналу @{CHANNEL_USERNAME}...", flush=True)
    last_id = load_last_id()
    is_initial_run = (last_id == 0)

    while True:
        try:
            messages = fetch_channel_messages()
            if messages:
                # Обробляємо повідомлення за порядком зростання ID
                for msg in messages:
                    if msg["id"] > last_id:
                        trains_label, clean_message = extract_train_lines(msg["text"])
                        if trains_label:
                            print(f"Знайдено поїзд: {trains_label} (повідомлення #{msg['id']})", flush=True)
                            
                            # При першому запуску перевіряємо історію, оновлюємо MQTT і надсилаємо сповіщення
                            send_telegram(clean_message)

                            mqtt_client.publish(MQTT_TOPIC_STATE, trains_label, retain=True)
                            payload = {
                                "train": trains_label,
                                "message": clean_message,
                                "date": msg["date"]
                            }
                            mqtt_client.publish(MQTT_TOPIC_ATTRS, json.dumps(payload, ensure_ascii=False), retain=True)

                        last_id = max(last_id, msg["id"])
                        save_last_id(last_id)
        except Exception as e:
            print(f"Помилка в циклі опитування: {e}", flush=True)

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
