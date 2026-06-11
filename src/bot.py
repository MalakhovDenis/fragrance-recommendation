import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from dotenv import load_dotenv

from scraper import FragranticaScraper
from recommender import PerfumeRecommender
from price_service import PriceService
from user_store import get_profile_id, set_profile_id, extract_profile_id

load_dotenv()

bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
dp = Dispatcher(storage=MemoryStorage())


class Setup(StatesGroup):
    waiting_for_profile = State()


def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="🔎 Получить рекомендации"))
    builder.row(types.KeyboardButton(text="⚙️ Изменить профиль"))
    return builder.as_markup(resize_keyboard=True)


@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    profile_id = get_profile_id(message.from_user.id)
    if profile_id:
        await message.answer(
            f"Привет! Твой профиль Fragrantica уже привязан (ID: {profile_id}).\n"
            "Нажми кнопку чтобы получить рекомендации.",
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
        "1. Открой сайт [fragrantica.ru](https://www.fragrantica.ru) и войди в аккаунт\n"
        "2. Перейди на свой профиль (иконка профиля → «Моя Fragrantica»)\n"
        "3. Скопируй ссылку из адресной строки\n"
        "   Она выглядит так: `https://www.fragrantica.ru/chlen/462653`\n\n"
        "Отправь эту ссылку сюда 👇",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


@dp.message(Setup.waiting_for_profile)
async def profile_received(message: types.Message, state: FSMContext):
    profile_id = extract_profile_id(message.text or "")
    if not profile_id:
        await message.answer(
            "❌ Не могу найти ID профиля в этом тексте.\n\n"
            "Нужна ссылка вида:\n`https://www.fragrantica.ru/chlen/462653`\n\n"
            "Попробуй ещё раз:",
            parse_mode="Markdown",
        )
        return

    status = await message.answer("⌛ Проверяю профиль...")

    # Проверяем что профиль существует и содержит ароматы
    try:
        scraper = FragranticaScraper()
        favorites = await scraper.get_favorites(profile_id)
    except Exception as e:
        await status.edit_text(
            f"❌ Не удалось загрузить профиль: {e}\n\n"
            "Убедись что ссылка верная и попробуй ещё раз."
        )
        return

    set_profile_id(message.from_user.id, profile_id)
    await state.clear()

    if favorites:
        names = ", ".join(p["name"] for p in favorites[:5])
        more = f" и ещё {len(favorites) - 5}" if len(favorites) > 5 else ""
        await status.edit_text(
            f"✅ Профиль привязан! Нашёл {len(favorites)} ароматов:\n"
            f"_{names}{more}_",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )
    else:
        await status.edit_text(
            "✅ Профиль привязан!\n\n"
            "😕 Гардероб пока пуст — добавь ароматы на Fragrantica "
            "(раздел «У меня есть» или «Я хочу»), и я подберу рекомендации.",
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
                "😕 Гардероб пуст.\n"
                "Добавь ароматы на Fragrantica в раздел «У меня есть» или «Я хочу»."
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


@dp.message(F.text & ~F.text.startswith("/"))
async def search_perfume_handler(message: types.Message, state: FSMContext):
    # Не реагируем на кнопки меню
    if message.text in ("🔎 Получить рекомендации", "⚙️ Изменить профиль"):
        return
    # Если ждём профиль — не перехватываем
    current_state = await state.get_state()
    if current_state == Setup.waiting_for_profile.state:
        return

    query = message.text.strip()
    status = await message.answer(f"🔍 Ищу «{query}» на Fragrantica...")

    try:
        scraper = FragranticaScraper()
        info = await scraper.search_perfume(query)

        if not info:
            await status.edit_text("😕 Ничего не найдено. Попробуй уточнить название или написать по-английски.")
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


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
