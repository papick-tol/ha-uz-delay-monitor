import html
import json
import os
import re
import time
import uuid
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
import requests

OPTIONS_FILE = "/data/options.json"
STATE_STORAGE = "/data/last_delays.json"

if os.path.exists(OPTIONS_FILE):
    with open(OPTIONS_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
else:
    raise RuntimeError("Конфігураційний файл /data/options.json відсутній!")

INTERVAL = int(config.get("check_interval_seconds", 60))
TG_BOT_TOKEN = config.get("tg_bot_token", "").strip()

raw_chat_ids = config.get("tg_chat_ids", [])
if isinstance(raw_chat_ids, int):
    TG_CHAT_IDS = [raw_chat_ids]
elif isinstance(raw_chat_ids, list):
    TG_CHAT_IDS = raw_chat_ids
else:
    TG_CHAT_IDS = []

TOPIC_PREFIX = config.get("mqtt_topic_prefix", "uz/train_delay").rstrip("/")

TRAIN_SCHEDULES = {
    str(item["train_id"]).strip(): str(item["schedule"]).strip()
    for item in config.get("train_schedules", [])
}

MQTT_TOPIC_STATE = f"{TOPIC_PREFIX}/state"
MQTT_TOPIC_ATTRS = f"{TOPIC_PREFIX}/attributes"

MQTT_BROKER = config.get("mqtt_broker") or os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(config.get("mqtt_port") or os.getenv("MQTT_PORT", 1883))
MQTT_USER = str(config.get("mqtt_user") or os.getenv("MQTT_USER", "")).strip()
MQTT_PASSWORD = str(config.get("mqtt_password") or os.getenv("MQTT_PASSWORD", "")).strip()

CLIENT_ID = f"uz_delay_monitor_{uuid.uuid4().hex[:8]}"
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)

if MQTT_USER and MQTT_PASSWORD:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

mqtt_connected = False

def on_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        print("MQTT: Підключено успішно.", flush=True)
    else:
        print(f"MQTT: Помилка з'єднання (rc={rc})", flush=True)

def on_disconnect(client, userdata, disconnect_flags, rc, properties=None):
    global mqtt_connected
    mqtt_connected = False

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect

try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"MQTT помилка підключення: {e}", flush=True)

# Очікуємо стабілізації підключення
wait_cycles = 0
while not mqtt_connected and wait_cycles < 20:
    time.sleep(0.5)
    wait_cycles += 1

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
            requests.post(url, data=data, timeout=25)
        except Exception as e:
            print(f"Помилка відправки Telegram ({chat_id}): {e}", flush=True)

def fetch_uz_vezemo_delays():
    """
    Завантажує та розбирає HTML-сторінку офіційного порталу suburban-delayform
    """
    url = "https://uz-vezemo.uz.gov.ua/suburban-delayform"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            print(f"uz-vezemo повернув HTTP {resp.status_code}", flush=True)
            return {}
    except Exception as err:
        print(f"Помилка запиту до uz-vezemo: {err}", flush=True)
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    page_text = soup.get_text(separator="\n")
    
    delays_found = {}

    # Шукаємо кожен поїзд із налаштованого списку
    for train_id in TRAIN_SCHEDULES.keys():
        escaped_id = re.escape(train_id)
        # Шукаємо рядок виду: 6723 Миронівка → Київ-Пас ... +1:37
        pattern = re.compile(
            rf"(?:№?\s*{escaped_id})\s+([^\n\+]+?)\s*(\+\d+:\d+|\+\d+\s*хв|\d+\s*хв)",
            re.IGNORECASE
        )
        match = pattern.search(page_text)
        if match:
            route = match.group(1).strip()
            delay = match.group(2).strip()
            delays_found[train_id] = {
                "route": route,
                "delay": delay
            }
            
    return delays_found

def load_cached_delays():
    if os.path.exists(STATE_STORAGE):
        try:
            with open(STATE_STORAGE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cached_delays(data):
    with open(STATE_STORAGE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def main():
    print("Запуск моніторингу затримок через uz-vezemo.uz.gov.ua...", flush=True)
    cached_delays = load_cached_delays()

    while True:
        try:
            current_delays = fetch_uz_vezemo_delays()
            
            # Якщо є виявлені затримки серед обраних рейсів
            if current_delays:
                active_trains = list(current_delays.keys())
                primary_train = active_trains[0]
                
                # Перевіряємо, чи змінився статус або час затримки
                has_updates = False
                messages = []
                
                for t_id, info in current_delays.items():
                    prev_info = cached_delays.get(t_id)
                    schedule = TRAIN_SCHEDULES.get(t_id, "")
                    
                    # Формуємо текст сповіщення
                    msg_body = (
                        f"🚆 Укрзалізниця (онлайн-моніторинг):\n"
                        f"Поїзд № {t_id} {info['route']}\n"
                        f"🕒 Графік: {schedule}\n"
                        f"⚠️ Затримка: {info['delay']}"
                    )
                    messages.append(msg_body)
                    
                    if not prev_info or prev_info.get("delay") != info["delay"]:
                        has_updates = True
                
                full_message = "\n\n".join(messages)

                # Якщо є нове повідомлення або затримка збільшилась/зменшилась
                if has_updates:
                    print(f"Знайдено оновлення: {', '.join(active_trains)} -> {current_delays}", flush=True)
                    send_telegram(full_message)

                    # Публікація в MQTT
                    try:
                        res_state = mqtt_client.publish(
                            MQTT_TOPIC_STATE, 
                            ", ".join(active_trains), 
                            retain=True, 
                            qos=1
                        )
                        res_state.wait_for_publish(timeout=5)

                        payload = {
                            "trains": active_trains,
                            "message": full_message,
                            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "details": current_delays
                        }
                        res_attrs = mqtt_client.publish(
                            MQTT_TOPIC_ATTRS, 
                            json.dumps(payload, ensure_ascii=False), 
                            retain=True, 
                            qos=1
                        )
                        res_attrs.wait_for_publish(timeout=5)
                        print(f"MQTT оновлено: {active_trains}", flush=True)
                    except Exception as mqtt_err:
                        print(f"Помилка публікації в MQTT: {mqtt_err}", flush=True)

                cached_delays = current_delays
                save_cached_delays(cached_delays)

            else:
                # Якщо раніше були затримки, а зараз сайт чистий (поїзди прибули)
                if cached_delays:
                    print("Затримок за вказаними рейсами немає. Скидання MQTT.", flush=True)
                    mqtt_client.publish(MQTT_TOPIC_STATE, "none", retain=True, qos=1)
                    mqtt_client.publish(MQTT_TOPIC_ATTRS, "{}", retain=True, qos=1)
                    cached_delays = {}
                    save_cached_delays(cached_delays)

        except Exception as e:
            print(f"Помилка в ітерації моніторингу: {e}", flush=True)

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
