import os
import asyncio
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
from groq import AsyncGroq

from scraper import FragranticaScraper
from recommender import PerfumeRecommender
from price_service import PriceService
from user_store import get_profile_id, set_profile_id, extract_profile_id

load_dotenv()

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher(storage=MemoryStorage())
groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))


class Setup(StatesGroup):
    waiting_for_profile = State()
    waiting_for_search = State()


def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="🔎 Получить рекомендации"))
    builder.row(
        types.KeyboardButton(text="🔍 Найти аромат"),
        types.KeyboardButton(text="⚙️ Изменить профиль"),
    )
    return builder.as_markup(resize_keyboard=True)


MENU_BUTTONS = {"🔎 Получить рекомендации", "🔍 Найти аромат", "⚙️ Изменить профиль"}


@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    profile_id = get_profile_id(message.from_user.id)
    if profile_id:
        await message.answer(
            "Привет! Я Духовед 🧴 — помогаю выбирать ароматы.\n\n"
            "Могу порекомендовать что-то по твоей полке, найти конкретный аромат "
            "или просто поговорить о парфюмерии. Чем помочь?",
            reply_markup=main_keyboard(),
        )
    else:
        await ask_for_profile(message, state)


@dp.message(F.text == "⚙️ Изменить профиль")
async def change_profile_handler(message: types.Message, state: FSMContext):
    await ask_for_profile(message, state)


async def ask_for_profile(message: types.Message, state: FSMContext):
    await state.set_state(Setup.waiting_for_profile)
    await message.answer(
        "📋 *Привяжи свой профиль Fragrantica*\n\n"
        "1. Открой [fragrantica.ru](https://www.fragrantica.ru) и войди в аккаунт\n"
        "2. Перейди на свой профиль (иконка → «Моя Fragrantica»)\n"
        "3. Скопируй ссылку из адресной строки:\n"
        "   `https://www.fragrantica.ru/chlen/462653`\n\n"
        "Отправь эту ссылку сюда 👇",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


@dp.message(Setup.waiting_for_profile)
async def profile_received(message: types.Message, state: FSMContext):
    profile_id = extract_profile_id(message.text or "")
    if not profile_id:
        await message.answer(
            "❌ Не могу найти ID профиля.\n\n"
            "Нужна ссылка вида:\n`https://www.fragrantica.ru/chlen/462653`\n\n"
            "Попробуй ещё раз:",
            parse_mode="Markdown",
        )
        return

    status = await message.answer("⌛ Проверяю профиль...")
    try:
        scraper = FragranticaScraper()
        favorites = await scraper.get_favorites(profile_id)
    except Exception as e:
        await status.edit_text(
            f"❌ Не удалось загрузить профиль: {e}\n\nУбедись что ссылка верная и попробуй ещё раз."
        )
        return

    set_profile_id(message.from_user.id, profile_id)
    await state.clear()

    if favorites:
        names = ", ".join(p["name"] for p in favorites[:5])
        more = f" и ещё {len(favorites) - 5}" if len(favorites) > 5 else ""
        await status.edit_text(
            f"✅ Профиль привязан! Нашёл {len(favorites)} ароматов:\n_{names}{more}_",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )
    else:
        await status.edit_text(
            "✅ Профиль привязан!\n\n😕 Гардероб пока пуст — добавь ароматы на Fragrantica.",
            reply_markup=main_keyboard(),
        )


@dp.message(F.text == "🔎 Получить рекомендации")
async def recommendations_handler(message: types.Message, state: FSMContext):
    profile_id = get_profile_id(message.from_user.id)
    if not profile_id:
        await ask_for_profile(message, state)
        return

    status_msg = await message.answer("⌛ Загружаю твоё избранное с Fragrantica...")

    try:
        scraper = FragranticaScraper()
        favorites = await scraper.get_favorites(profile_id)

        if not favorites:
            await status_msg.edit_text(
                "😕 Гардероб пуст. Добавь ароматы на Fragrantica в раздел «У меня есть»."
            )
            return

        preview = favorites[:10]
        fav_names = ", ".join(p["name"] for p in preview)
        more = f" и ещё {len(favorites) - 10}" if len(favorites) > 10 else ""
        await status_msg.edit_text(
            f"🤖 Анализирую вкус ({len(favorites)} ароматов)...\n_{fav_names}{more}_",
            parse_mode="Markdown",
        )

        recommender = PerfumeRecommender()
        recommendations = await recommender.get_recommendations(favorites)

        await status_msg.edit_text("💰 Ищу цены на АллюрПарфюм...")

        price_service = PriceService()
        prices_list = await asyncio.gather(
            *[price_service.fetch_prices(rec["name"]) for rec in recommendations["recommendations"]],
        )

        await status_msg.delete()

        for rec, price_info in zip(recommendations["recommendations"], prices_list):
            fragrantica_url = PriceService.get_fragrantica_url(rec["name"])
            search_url = PriceService.get_search_url(rec["name"])

            if price_info and price_info.get("price_per_ml"):
                avail = "✅" if price_info["available"] else "⏳"
                vol = int(price_info["volume_ml"]) if price_info["volume_ml"] == int(price_info["volume_ml"]) else price_info["volume_ml"]
                price_line = (
                    f"💊 [АллюрПарфюм: {price_info['price_rub']}₽/{vol}мл "
                    f"({price_info['price_per_ml']}₽/мл) {avail}]({price_info['url']})"
                )
            else:
                price_line = f"💊 [АллюрПарфюм: смотреть пробники]({search_url})"

            text = (
                f"✨ *{rec['name']}*\n\n"
                f"📝 {rec['reason']}\n\n"
                f"👃 *Ноты:* {rec['notes']}\n\n"
                f"🔗 [Fragrantica]({fragrantica_url})\n"
                f"{price_line}"
            )
            await message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as e:
        await status_msg.delete()
        await message.answer(f"❌ Ошибка: {e}")
        if os.path.exists("error.png"):
            await message.answer_photo(types.FSInputFile("error.png"), caption="Скриншот ошибки")
            os.remove("error.png")


@dp.message(F.text == "🔍 Найти аромат")
async def search_button_handler(message: types.Message, state: FSMContext):
    await state.set_state(Setup.waiting_for_search)
    await message.answer(
        "🔍 Напиши название аромата — точное или приблизительное, на русском или английском:",
        reply_markup=types.ReplyKeyboardRemove(),
    )


@dp.message(Setup.waiting_for_search)
async def search_query_received(message: types.Message, state: FSMContext):
    await state.clear()
    query = message.text.strip()
    await _do_perfume_search(message, query)


async def _do_perfume_search(message: types.Message, query: str):
    status = await message.answer(f"🔍 Ищу «{query}»...", reply_markup=main_keyboard())

    try:
        scraper = FragranticaScraper()
        info = await scraper.search_perfume(query)

        if not info:
            await status.edit_text(
                "😕 Ничего не найдено. Попробуй уточнить название.",
                reply_markup=main_keyboard(),
            )
            return

        await status.edit_text("💰 Ищу цену на АллюрПарфюм...")

        price_service = PriceService()
        price_info = await price_service.fetch_prices(info["name"])

        notes_str = info.get("notes_text") or "нет данных"
        year_str = f" ({info['year']})" if info.get("year") else ""

        if price_info and price_info.get("price_per_ml"):
            avail = "✅ в наличии" if price_info["available"] else "⏳ нет в наличии"
            vol = int(price_info["volume_ml"]) if price_info["volume_ml"] == int(price_info["volume_ml"]) else price_info["volume_ml"]
            price_str = f"[{price_info['price_rub']}₽/{vol}мл · {price_info['price_per_ml']}₽/мл · {avail}]({price_info['url']})"
        else:
            search_url = PriceService.get_search_url(info["name"])
            price_str = f"[смотреть пробники]({search_url})"

        caption = (
            f"*{info['name']}*{year_str}\n\n"
            f"👃 *Ноты:*\n{notes_str}\n\n"
            f"💊 *АллюрПарфюм:* {price_str}\n\n"
            f"🔗 [Открыть на Fragrantica]({info['url']})"
        )

        await status.delete()

        image_url = price_info.get("image_url") if price_info else None
        if image_url:
            await message.answer_photo(
                photo=image_url,
                caption=caption,
                parse_mode="Markdown",
            )
        else:
            await message.answer(caption, parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as e:
        await status.edit_text(f"❌ Ошибка: {e}")


async def _chat_with_ai(message: types.Message, state: FSMContext):
    """Естественный диалог о парфюмерии через Groq."""
    # Сохраняем историю в FSM state (последние 10 сообщений)
    data = await state.get_data()
    history = data.get("chat_history", [])

    history.append({"role": "user", "content": message.text})
    if len(history) > 20:
        history = history[-20:]

    system = (
        "Ты Духовед — эксперт-парфюмер и дружелюбный консультант по ароматам. "
        "Отвечаешь кратко и по делу, на русском языке. "
        "Знаешь всё о парфюмерии: ноты, бренды, тенденции, стойкость, сезонность. "
        "Если пользователь спрашивает про конкретный аромат, предлагаешь нажать кнопку '🔍 Найти аромат' чтобы получить цены."
    )

    try:
        typing_msg = await message.answer("...")
        response = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system}] + history,
            temperature=0.8,
            max_tokens=512,
        )
        reply = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply})
        await state.update_data(chat_history=history)
        await typing_msg.edit_text(reply)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@dp.message(F.text & ~F.text.startswith("/"))
async def text_handler(message: types.Message, state: FSMContext):
    if message.text in MENU_BUTTONS:
        return
    current_state = await state.get_state()
    if current_state in (Setup.waiting_for_profile.state, Setup.waiting_for_search.state):
        return
    await _chat_with_ai(message, state)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
