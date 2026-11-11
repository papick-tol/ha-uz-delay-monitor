# 🚆 UZ Train Delay Monitor (Home Assistant Add-on)

Гібридний додаток для Home Assistant OS, який моніторить затримки приміських поїздів Укрзалізниці одночасно з двох джерел: публічної веб-стрічки Telegram-каналу (@UZprymisky) та офіційного сервісу **UZ Vezemo** (`uz-vezemo.uz.gov.ua`).

Додаток виявляє затримки за вашим персональним списком поїздів, автоматично відсікає чужі регіони та застарілі рейси, публікує актуальний стан і розширені атрибути в MQTT для легкого виведення на дашборд Lovelace та гнучкої маршрутизації сповіщень.

---

## ✨ Особливості

- 🛰️ **Гібридний моніторинг**: Поєднує оперативні текстові зведення з Telegram та точні табличні дані з офіційного сайту UZ Vezemo.
- 🚀 **Працює без API-ключів**: Не вимагає облікового запису розробника Telegram (`api_id`, `api_hash`) чи авторизації — використовує публічні веб-інтерфейси.
- 🎯 **Захист від фантомних затримок з інших областей**: Фільтрація за чорним (`ignored_keywords`) та білим (`allowed_keywords`) списками станцій, щоб однакові номери поїздів з інших залізниць (наприклад, Харківщини) не потрапляли у ваші сповіщення.
- ⏱️ **Фільтр незначних затримок**: Можливість задати мінімальний поріг у хвилинах (`min_delay_minutes`), щоб не отримувати сповіщення про зміщення графіка на 1–2 хвилини.
- 🕒 **Автопідстановка розкладу та контроль завершення рейсу**: Додає час графіка безпосередньо в текст та автоматично припиняє моніторинг рейсу через 90 хвилин після його планового прибуття.
- 📊 **Повна інтеграція з MQTT**: Публікує стан (`state`) та структурований JSON з атрибутами (`attributes`, включно з порейсовим словником `details`) для надійної маршрутизації в автоматизаціях.

---

## 📦 Встановлення

1. У веб-інтерфейсі Home Assistant відкрийте:  
   **Параметри** (*Settings*) → **Додатки** (*Add-ons*) → **Магазин додатків** (*Add-on Store*).
2. У правому верхньому кутку натисніть меню (три крапки) → **Репозиторії** (*Repositories*).
3. Додайте посилання на цей GitHub-репозиторій і натисніть **Додати** (*Add*).
4. Оновіть список додатків (меню три крапки → **Перевірити оновлення** / *Check for updates*).
5. Знайдіть у списку **UZ Train Delay Monitor** та натисніть **Встановити** (*Install*).

---

## ⚙️ Налаштування (Configuration)

Приклад повної конфігурації у вкладці **Конфігурація** (*Configuration*):

```yaml
channel_username: "UZprymisky"
check_interval_seconds: 60
mqtt_broker: "core-mosquitto"
mqtt_port: 1883
mqtt_user: "YourUser"
mqtt_password: "YourPassword"
mqtt_topic_prefix: "uz/train_delay"
min_delay_minutes: 5
ignored_keywords:
  - "харків"
  - "зміїв"
  - "люботин"
  - "полтава"
  - "дніпро"
  - "львів"
  - "одеса"
allowed_keywords:
  - "київ"
  - "миронівка"
  - "трипілля"
  - "ніжин"
  - "дарниця"
  - "фастів"
train_schedules:
  - train_id: "6701"
    schedule: "8:44 -> 10:00"
  - train_id: "6703"
    schedule: "12:52 -> 13:43"
  - train_id: "6705"
    schedule: "18:13 -> 19:05"
  - train_id: "6721"
    schedule: "6:00 -> 7:14"
  - train_id: "6723"
    schedule: "9:34 -> 10:35"
  - train_id: "6725"
    schedule: "16:21 -> 17:38"
  - train_id: "6912"
    schedule: "15:43 -> 17:10"
```
# 🏠 Інтеграція в Home Assistant
1. Додавання MQTT-сенсора

Додайте у ваш configuration.yaml (або mqtt.yaml):
YAML

``` mqtt:
  sensor:
    - name: "UZ Train Delay"
      unique_id: uz_train_delay
      state_topic: "uz/train_delay/state"
      json_attributes_topic: "uz/train_delay/attributes"
      icon: "mdi:train"
```
Перезавантажте MQTT-сутності через: Інструменти розробника → вкладка YAML → Вручну налаштовані сутності MQTT.
2. Приклад картки для Lovelace

Картка Markdown, яка відображається лише за наявності активних затримок:
``` YAML
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
  {% set updated = state_attr('sensor.uz_train_delay', 'updated_at') %}
  {% if msg %}
  {{ msg.replace('🚆 Укрзалізниця: Затримка\n', '').replace('\n', '<br>') }}

  <small>Останнє оновлення: {{ updated if updated else 'Не вказано' }}</small>
  {% endif %}
```
# Опис параметрів: 
| Параметр | Тип | Опис |
| :--- | :--- | :--- |
| `channel_username` | Рядок | Назва Telegram-каналу для парсингу (за замовчуванням `UZprymisky`). |
| `check_interval_seconds` | Число | Інтервал опитування сервісів у секундах (рекомендовано 30–60). |
| `mqtt_broker` | Рядок | Хост брокера MQTT (`core-mosquitto` для внутрішнього Mosquitto в HA). |
| `mqtt_port` | Число | Порт MQTT (зазвичай `1883`). |
| `mqtt_user` / `mqtt_password` | Рядок | Облікові дані для підключення до MQTT. |
| `mqtt_topic_prefix` | Рядок | Префікс топіків для публікації даних (за замовчуванням `uz/train_delay`). |
| `min_delay_minutes` | Число | *(Опціонально)* Мінімальний поріг затримки у хвилинах для надсилання сповіщення. Якщо час уточнюється, повідомлення публікується незалежно від порогу. |
| `ignored_keywords` | Список | *(Опціонально)* Чорний список назв міст/станцій для відсікання однойменних рейсів з інших дирекцій УЗ (наприклад, Харків, Зміїв). |
| `allowed_keywords` | Список | *(Опціонально)* Білий список міст/станцій вашого регіону. |
| `train_schedules` | Список | Перелік відстежуваних номерів поїздів та їхній штатний розклад. |


### 3. Автоматизація для сповіщень у Telegram

Щоб отримувати повідомлення про нові або змінені затримки в Telegram, створіть автоматизацію в Home Assistant.

#### Варіант А: Через стандартну інтеграцію Telegram (`notify.telegram_...`)

Якщо у вас налаштовано базову службу сповіщень:

```yaml
alias: "UZ: Сповіщення про затримки в Telegram"
trigger:
  - trigger: state
    entity_id: sensor.uz_train_delay
    to: null
condition:
  # Ігноруємо пустий стан, відсутність даних або скидання
  - condition: template
    value_template: >-
      {{ states('sensor.uz_train_delay') not in ['none', 'unknown', 'unavailable', ''] }}
action:
  - action: notify.telegram_chat
    data:
      message: "{{ state_attr('sensor.uz_train_delay', 'message') }}"
mode: single
```
#### Варіант Б: Пряма відправка через REST API бота (без інтеграції Telegram)

Якщо ви використовуєте окремого бота без попереднього налаштування інтеграції Telegram у Home Assistant, повідомлення можна надсилати через прямий виклик `rest_command`.

1. Додайте у файл `configuration.yaml`:

```yaml
rest_command:
  telegram_send:
    url: "[https://api.telegram.org/bot](https://api.telegram.org/bot){{ bot_token }}/sendMessage"
    method: POST
    content_type: "application/json"
    payload: >-
      {"chat_id": "{{ chat_id }}", "text": {{ message | to_json }}}


```
2. Додайте у файл `configuration.yaml`:
```yaml
 alias: "UZ: Сповіщення через REST Telegram"
 trigger:
   - trigger: state
     entity_id: sensor.uz_train_delay
     to: null
 condition:
   - condition: template
     value_template: >-
       {{ states('sensor.uz_train_delay') not in ['none', 'unknown', 'unavailable', ''] }}
 action:
   - action: rest_command.telegram_send
     data:
       bot_token: "ВАШ_ТОКЕН_БОТА"
       chat_id: "ВАШ_CHAT_ID"
       message: "{{ state_attr('sensor.uz_train_delay', 'message') }}"
mode: single
```
