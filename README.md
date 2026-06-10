# Fragrantica Perfume Bot

Telegram-бот, который анализирует твой гардероб на Fragrantica и рекомендует новые ароматы с ценами от allureparfum.ru.

## Что делает бот

1. Загружает ароматы из гардероба пользователя на Fragrantica (секции «У меня есть», «Я хочу», «У меня были», «Попробовать»)
2. Через ИИ (Llama 3.3 70B, бесплатно) подбирает 3 похожих/интересных аромата
3. Ищет цену пробника на allureparfum.ru и показывает стоимость за 1 мл

## Структура проекта

```
pr1/
├── src/
│   ├── bot.py            # Telegram-бот (aiogram 3.x, FSM)
│   ├── scraper.py        # Парсинг Fragrantica (Playwright + CF-куки)
│   ├── recommender.py    # ИИ-рекомендации (Groq / Llama 3.3 70B)
│   ├── price_service.py  # Цены с allureparfum.ru
│   └── user_store.py     # Хранение Telegram ID → Fragrantica ID
├── data/
│   └── users.json        # База пользователей
├── .env                  # Токены и ключи
└── requirements.txt
```

## Зависимости

```
aiogram>=3.0
playwright
browser_cookie3
beautifulsoup4
groq
python-dotenv
```

Установка:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Настройка

### .env

```env
TELEGRAM_BOT_TOKEN=...
GROQ_API_KEY=...
```

Groq API бесплатен: https://console.groq.com

### Добавление пользователей

Пользователи хранятся в `data/users.json` в формате:

```json
{
  "TELEGRAM_ID": "FRAGRANTICA_PROFILE_ID"
}
```

Fragrantica ID — число из URL профиля: `fragrantica.ru/chlen/462653` → `462653`.  
Telegram ID можно узнать через [@userinfobot](https://t.me/userinfobot) или переслав сообщение пользователя туда.

Новые пользователи также могут привязать профиль самостоятельно через команду `/start`.

## Запуск

```bash
source venv/bin/activate
python src/bot.py
```

Или в фоне:

```bash
nohup python src/bot.py > bot.log 2>&1 &
```

## Как работает парсинг Fragrantica

Сайт защищён Cloudflare. Бот обходит защиту, используя CF-куки из установленного Chrome на машине (`browser_cookie3`). Куки `cf_clearance`, `_ga` и другие берутся автоматически — никакой авторизации не нужно, профили публичны.

После загрузки страницы бот ждёт появления секций гардероба (они рендерятся через JS ~1 сек), затем парсит ссылки на ароматы.

**Требование:** на машине должен быть установлен Chrome и пользователь хотя бы раз заходил на fragrantica.ru — чтобы CF-куки были в браузере.

## Как работают рекомендации

Список ароматов из гардероба передаётся в промпт модели Llama 3.3 70B через Groq API. Модель возвращает 3 рекомендации в JSON: название, причина, ноты. Groq предоставляет бесплатный доступ к модели.

## Как работает поиск цен

Бот ищет аромат на allureparfum.ru через `/search/?q=`. Из результатов выбирает товар с максимальным совпадением слов названия с URL товара (минимум 2 совпадения). На странице товара ищет пробник объёмом ≤ 10 мл в наличии и считает цену за 1 мл.

## Команды бота

| Команда / Кнопка | Действие |
|---|---|
| `/start` | Приветствие, привязка профиля Fragrantica |
| `🔎 Получить рекомендации` | Загрузить гардероб и получить 3 рекомендации |
| `⚙️ Изменить профиль` | Привязать другой профиль Fragrantica |
