# 🚆 UZ Train Delay Monitor (Home Assistant Add-on)

Додаток для **Home Assistant OS**, який відстежує офіційний Telegram-канал приміських поїздів Укрзалізниці ([@UZprymisky](https://t.me/UZprymisky)), виявляє затримки за вашим персональним списком поїздів, публікує актуальний стан в **MQTT** та надсилає персоналізовані сповіщення з розкладом в **Telegram**.

---

## ✨ Особливості

* 🚀 **Працює «з нуля»**: Не вимагає облікового запису розробника Telegram (`api_id`, `api_hash`) чи SMS-авторизації — парсить публічну стрічку каналу без ризику блокування сесій.
* 🕒 **Автопідстановка розкладу**: Додає звичний вам час відправлення та прибуття безпосередньо в текст сповіщення перед інформацією про затримку.
* 📢 **Окремий Telegram-бот**: Можливість надсилати сповіщення як одному, так і кільком користувачам або групам одночасно.
* 📊 **Інтеграція з MQTT**: Публікує стан (`state`) та розширені атрибути (`attributes`) для виведення на дашборд Lovelace.
* 🔄 **Перевірка історії при старті**: Під час запуску або перезавантаження перевіряє останні публікації, щоб не пропустити актуальні затримки.

---

## 📦 Встановлення

1. У веб-інтерфейсі Home Assistant перейдіть у меню:  
   **Налаштування (Settings)** → **Додатки (Add-ons)** → **Магазин додатків (Add-on Store)**.
2. У правому верхньому кутку натисніть меню (три крапки) → **Репозиторії (Repositories)**.
3. Додайте посилання на цей GitHub-репозиторій і натисніть **Додати (Add)**.
```
https://github.com/papick-tol/ha-uz-delay-monitor
```
5. Оновіть сторінку магазину або натисніть меню (три крапки) → **Перевірити оновлення (Check for updates)**.
6. У списку репозиторіїв знайдіть **UZ Train Delay Monitor** і натисніть **Встановити (Install)**.

---

## ⚙️ Налаштування (Configuration)

Після встановлення відкрийте вкладку **Конфігурація (Configuration)** аддона:

```yaml
channel_username: "UZprymisky"
check_interval_seconds: 30
tg_bot_token: "1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ"
tg_chat_ids:
  - 123456789
  - 987654321
mqtt_topic_prefix: "uz/train_delay"
train_schedules:
  - train_id: "6702/6701"
    schedule: "8:44 -> 10:00"
  - train_id: "6704/6703"
    schedule: "12:52 -> 13:43"
  - train_id: "6911"
    schedule: "7:09 -> 8:03"
  - train_id: "897 1"
    schedule: "15:43 -> 16:21"
```
## Опис параметрів:

    channel_username: Назва Telegram-каналу для моніторингу (за замовчуванням UZprymisky, без символу @).

    check_interval_seconds: Інтервал опитування каналу в секундах (рекомендовано 30–60).

    tg_bot_token: Токен вашого Telegram-бота, отриманий від @BotFather (необов'язково, якщо використовуєте сповіщення виключно через Home Assistant).

    tg_chat_ids: Список числових ідентифікаторів чатів користувачів або груп, куди бот надсилатиме повідомлення.
'''
Якщо тільки один користувач:
У правому верхньому кутку сторінки конфігурації аддона натисніть меню (три крапки) → Edit in YAML (Редагувати в YAML) і вкажіть ID списком із дефісом:
```
  tg_chat_ids:
  - 576912424
```
  (Користувач обов'язково повинен попередньо натиснути /start у діалозі з ботом).

    mqtt_topic_prefix: Префікс топіків для публікації даних у вашому брокері Mosquitto (за замовчуванням uz/train_delay).

    train_schedules: Список поїздів, які вас цікавлять, та їхній розклад. Скрипт шукає номери з цього списку у повідомленнях каналу.

🏠 Інтеграція в Home Assistant
1. Додавання MQTT-сенсора

Додайте у ваш файл configuration.yaml (або mqtt.yaml):
```
mqtt:
  sensor:
    - name: "UZ Train Delay"
      unique_id: uz_train_delay
      state_topic: "uz/train_delay/state"
      icon: "mdi:train"
      json_attributes_topic: "uz/train_delay/attributes"
```
Перезавантажте сутності MQTT у Інструменти розробника → YAML → Manually configured MQTT entities.
2. Скидання стану вночі (Автоматизація)

Щоб учорашні затримки не висіли на дашборді зранку, створіть автоматизацію, яка щоночі очищає сенсор:
```
alias: "UZ: Скидання затримок о 03:00"
trigger:
  - trigger: time
    at: "03:00:00"
action:
  - action: mqtt.publish
    data:
      topic: "uz/train_delay/state"
      payload: "none"
      retain: true
  - action: mqtt.publish
    data:
      topic: "uz/train_delay/attributes"
      payload: "{}"
      retain: true
```
Картка для Lovelace (з'являється лише при наявності затримок)

Додайте картку типу Markdown на ваш дашборд:
```
type: markdown
visibility:
  - condition: state
    entity: sensor.uz_train_delay
    state_not: unknown
  - condition: state
    entity: sensor.uz_train_delay
    state_not: unavailable
  - condition: state
    entity: sensor.uz_train_delay
    state_not: "none"
content: |
  {% set msg = state_attr('sensor.uz_train_delay', 'message') %}
  {% set time = state_attr('sensor.uz_train_delay', 'date') %}
  {% if msg %}
  {{ msg.replace('🚆 Укрзалізниця: Затримка\n', '').replace('\n', '<br>') }}

  Час фіксації: {{ time if time else 'Не вказано' }}
  {% endif %}
