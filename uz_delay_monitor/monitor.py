import html
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
import requests

OPTIONS_FILE = "/data/options.json"
STATE_FILE = "/data/last_delays.json"

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

if os.path.exists(OPTIONS_FILE):
    try:
        with open(OPTIONS_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        log(f"Помилка читання {OPTIONS_FILE}: {e}")
        config = {}
else:
    config = {}

INTERVAL = int(config.get("check_interval_seconds", 30))
TOPIC_PREFIX = config.get("mqtt_topic_prefix", "uz/train_delay").rstrip("/")

MQTT_TOPIC_STATE = f"{TOPIC_PREFIX}/state"
MQTT_TOPIC_ATTRS = f"{TOPIC_PREFIX}/attributes"

MQTT_BROKER = config.get("mqtt_broker") or os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(config.get("mqtt_port") or os.getenv("MQTT_PORT", 1883))
MQTT_USER = str(config.get("mqtt_user") or os.getenv("MQTT_USER", "")).strip()
MQTT_PASSWORD = str(config.get("mqtt_password") or os.getenv("MQTT_PASSWORD", "")).strip()

raw_schedules = config.get("train_schedules", [])
TRAIN_SCHEDULES = {}
for item in raw_schedules:
    t_id = str(item.get("train_id", "")).strip()
    sch = str(item.get("schedule", "")).strip()
    if t_id:
        TRAIN_SCHEDULES[t_id] = sch

log(f"Відстежувані поїзди: {list(TRAIN_SCHEDULES.keys())}")

sorted_keys = sorted(TRAIN_SCHEDULES.keys(), key=len, reverse=True)
TRAIN_PATTERN = (
    re.compile(r"(" + "|".join([re.escape(x) for x in sorted_keys]) + r")")
    if sorted_keys
    else None
)

CLIENT_ID = f"uz_delay_monitor_{uuid.uuid4().hex[:8]}"
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)

if MQTT_USER and MQTT_PASSWORD:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

mqtt_connected = False

def on_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        log("MQTT: Підключено успішно.")
    else:
        log(f"MQTT: Помилка з'єднання (rc={rc})")

def on_disconnect(client, userdata, disconnect_flags, rc, properties=None):
    global mqtt_connected
    mqtt_connected = False
    log(f"MQTT: Відключено (rc={rc})")

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect

try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()
except Exception as e:
    log(f"MQTT помилка підключення: {e}")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
}

def is_train_relevant(train_id):
    """
    Перевіряє, чи рейс ще актуальний за часом.
    Якщо плановий час прибуття минув понад 90 хвилин тому — рейс вважається завершеним.
    """
    schedule = TRAIN_SCHEDULES.get(train_id, "").strip()
    if not schedule:
        return True

    # Парсимо час у форматі "8:44 -> 10:00" або "08:44-10:00"
    times = re.findall(r"(\d{1,2}:\d{2})", schedule)
    if len(times) < 2:
        return True

    try:
        now = datetime.now()
        dep_str, arr_str = times[0], times[1]

        dep_dt = datetime.strptime(dep_str, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
        arr_dt = datetime.strptime(arr_str, "%H:%M").replace(year=now.year, month=now.month, day=now.day)

        # Якщо рейс нічний (прибуття наступного дня)
        if arr_dt < dep_dt:
            arr_dt += timedelta(days=1)

        # Дозволяємо публікувати до 90 хв після планового прибуття
        expiration_time = arr_dt + timedelta(minutes=120)

        # Якщо зараз сильно пізніше часу прибуття або ще зарано (більше ніж за 2 години до відправки)
        if now > expiration_time:
            return False

        earliest_monitoring_time = dep_dt - timedelta(hours=2)
        if now < earliest_monitoring_time:
            return False

        return True
    except Exception as e:
        log(f"Помилка перевірки графіка для {train_id}: {e}")
        return True

def format_train_message(line, train_id, delay_val=None):
    schedule = TRAIN_SCHEDULES.get(train_id, "").strip()
    clean_line = line.replace("**", "").strip()
    clean_line = re.sub(r"^[🚊🚆➡️\s]+", "", clean_line)

    # Видаляємо старі хвости про затримку, щоб сформувати стандартний блок
    clean_route = re.sub(r"\s*(затримка|курсує).*$", "", clean_line, flags=re.IGNORECASE).strip()

    if delay_val:
        d_str = str(delay_val).strip()
        if d_str in ["0", "+0:00", "0:00", "+0", "None", ""]:
            delay_line = "⚠️ затримка: час уточнюється"
        else:
            delay_line = f"⚠️ затримка {d_str if d_str.startswith('+') else '+' + d_str}"
    else:
        # Шукаємо в тексті рядка
        delay_match = re.search(r"затримка\s*([\+\d\:\w\s]+)", clean_line, re.IGNORECASE)
        if delay_match:
            val = delay_match.group(1).strip()
            delay_line = f"⚠️ затримка {val}"
        else:
            delay_line = "⚠️ затримка: час уточнюється"

    sched_block = f"\n🕒 Графік: {schedule}" if schedule else ""
    return f"🚆 Укрзалізниця: Затримка\n{clean_route}{sched_block}\n{delay_line}"

def check_uz_vezemo():
    if not TRAIN_SCHEDULES:
        return {}

    url = "https://uz-vezemo.uz.gov.ua/suburban-delayform"
    results = {}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log(f"uz-vezemo HTTP код: {resp.status_code}")
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.find_all("tr", class_=lambda c: c and "delay-row" in c)

        for row in rows:
            num_tag = row.find(class_="js-delay-train-number")
            if not num_tag:
                continue

            train_num = num_tag.get_text().strip()
            data_search = num_tag.get("data-search", "")

            matched_id = None
            for my_id in TRAIN_SCHEDULES.keys():
                if my_id == train_num or my_id in data_search:
                    matched_id = my_id
                    break

            if matched_id:
                # Перевіряємо, чи актуальний рейс за часом
                if not is_train_relevant(matched_id):
                    continue

                conn_tag = row.find(class_=lambda c: c and "js-delay-connections" in c)
                route = " ".join(conn_tag.get_text().split()) if conn_tag else ""
                row_text = " ".join(row.get_text().split())

                # Шукаємо час затримки
                delay_match = re.search(r"(\+\s*\d+:\d+|\+\s*\d+\s*хв|\d+\s*хв)", row_text)
                if delay_match:
                    delay_val = delay_match.group(1).replace(" ", "")
                else:
                    delay_val = "час уточнюється"

                if route:
                    line = f"{matched_id} {route}"
                else:
                    line = f"{matched_id}"

                formatted = format_train_message(line, matched_id, delay_val)

                results[matched_id] = {
                    "source": "uz-vezemo",
                    "raw": f"{matched_id} {delay_val}",
                    "delay": delay_val,
                    "message": formatted
                }
    except Exception as e:
        log(f"Помилка опитування uz-vezemo: {e}")

    return results

def check_telegram():
    if not TRAIN_PATTERN:
        return {}

    url = "https://t.me/s/UZprymisky"
    results = {}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        messages = soup.find_all("div", class_="tgme_widget_message_text")
        if not messages:
            return {}

        recent_posts = list(reversed(messages[-15:]))
        for post in recent_posts:
            text = post.get_text(separator="\n")
            for raw_line in text.splitlines():
                line = raw_line.strip()
                match = TRAIN_PATTERN.search(line)
                if match:
                    train_id = match.group(1)

                    # Перевіряємо за часом розкладу
                    if not is_train_relevant(train_id):
                        continue

                    if train_id not in results:
                        # Спробуємо витягнути затримку з рядка TG
                        delay_match = re.search(r"(\+\s*\d+:\d+|\+\s*\d+\s*хв|\d+\s*хв)", line)
                        delay_val = delay_match.group(1).replace(" ", "") if delay_match else "час уточнюється"

                        formatted = format_train_message(line, train_id, delay_val)
                        results[train_id] = {
                            "source": "telegram",
                            "raw": f"{train_id} {delay_val}",
                            "delay": delay_val,
                            "message": formatted
                        }
    except Exception as e:
        log(f"Помилка опитування Telegram: {e}")

    return results

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        log(f"Не вдалося зберегти стан: {e}")

def main():
    log("Запуск гібридного UZ Monitor (Telegram Web + uz-vezemo)...")
    last_state = load_state()
    empty_checks_count = 0

    while True:
        try:
            tg_delays = check_telegram()
            web_delays = check_uz_vezemo()

            combined_delays = {}
            # Веб має пріоритет над Telegram щодо точності часу затримки
            combined_delays.update(tg_delays)
            combined_delays.update(web_delays)

            found_info = []
            if web_delays:
                found_info.append(f"Web: {list(web_delays.keys())}")
            if tg_delays:
                found_info.append(f"TG: {list(tg_delays.keys())}")
            
            if found_info:
                log(f"Знайдено затримки -> {', '.join(found_info)}")
            else:
                log("Опитування завершено: актуальних затримок не виявлено.")

            if combined_delays:
                empty_checks_count = 0
                active_trains = list(combined_delays.keys())
                messages = [v["message"] for v in combined_delays.values()]
                full_message = "\n\n".join(messages)

                state_val = ", ".join([f"{t_id} ({data.get('delay', 'затримка')})" for t_id, data in combined_delays.items()])

                # Перевіряємо, чи змінився склад поїздів або значення затримки
                has_changed = False
                if set(active_trains) != set(last_state.keys()):
                    has_changed = True
                else:
                    for t_id, data in combined_delays.items():
                        if last_state.get(t_id, {}).get("raw") != data.get("raw"):
                            has_changed = True
                            break

                if has_changed:
                    payload = {
                        "trains": active_trains,
                        "message": full_message,
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "details": combined_delays
                    }

                    log(f"Публікація в MQTT -> Стан: '{state_val}'")
                    mqtt_client.publish(MQTT_TOPIC_ATTRS, json.dumps(payload, ensure_ascii=False), retain=True, qos=1)
                    mqtt_client.publish(MQTT_TOPIC_STATE, state_val, retain=True, qos=1)

                    last_state = combined_delays
                    save_state(last_state)

            else:
                if last_state:
                    empty_checks_count += 1
                    if empty_checks_count >= 2:
                        log("Затримок більше немає (підтверджено). Скидання MQTT в 'none'.")
                        mqtt_client.publish(MQTT_TOPIC_ATTRS, "{}", retain=True, qos=1)
                        mqtt_client.publish(MQTT_TOPIC_STATE, "none", retain=True, qos=1)
                        last_state = {}
                        save_state(last_state)
                        empty_checks_count = 0
                    else:
                        log("Дані відсутні у поточному запиті, очікування підтвердження...")

        except Exception as e:
            log(f"Помилка головного циклу: {e}")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
