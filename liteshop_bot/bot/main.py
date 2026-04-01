import asyncio
import json
import math
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
STARS_RATE = float(os.getenv("STARS_RATE", "1.8"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")

if not ADMIN_ID:
    raise ValueError("ADMIN_ID не найден в .env")

if not WEBAPP_URL:
    raise ValueError("WEBAPP_URL не найден в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_orders: dict[int, dict] = {}


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Открыть магазин",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ],
        resize_keyboard=True,
    )


def payment_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Оплатить Stars")],
            [KeyboardButton(text="Оплатить Crypto")],
            [KeyboardButton(text="В меню")],
        ],
        resize_keyboard=True,
    )


def format_order_text(items: list[dict], total_rub: float) -> str:
    lines = ["Новый заказ", ""]
    for item in items:
        lines.append(f"• {item.get('title', 'Товар')} x{item.get('qty', 1)} — {item.get('line_total_rub', 0)} ₽")
    lines.extend(["", f"Итого: {total_rub} ₽"])
    return "\n".join(lines)


def format_admin_user(user) -> str:
    username = f"@{user.username}" if user.username else "нет username"
    return f"Пользователь: {user.full_name}\nID: {user.id}\nUsername: {username}"


def format_admin_order_text(user, items: list[dict], total_rub: float, total_stars: int) -> str:
    lines = ["НОВЫЙ ЗАКАЗ", "", format_admin_user(user), "", "Товары:"]
    for item in items:
        lines.append(
            f"• {item.get('title', 'Товар')} ({item.get('category', 'Без категории')}) "
            f"x{item.get('qty', 1)} — {item.get('line_total_rub', 0)} ₽"
        )
    lines.extend(["", f"Сумма в рублях: {total_rub} ₽", f"Сумма в Stars: {total_stars}", f"Курс: {STARS_RATE} Stars = 1 ₽"])
    return "\n".join(lines)


def format_admin_paid_text(user, order: dict | None, stars_paid: int) -> str:
    lines = ["ОПЛАТА ПРОШЛА УСПЕШНО", "", format_admin_user(user), ""]
    if order:
        lines.append("Оплаченные товары:")
        for item in order.get("items", []):
            lines.append(
                f"• {item.get('title', 'Товар')} ({item.get('category', 'Без категории')}) "
                f"x{item.get('qty', 1)} — {item.get('line_total_rub', 0)} ₽"
            )
        lines.append("")
        lines.append(f"Сумма заказа: {order.get('total_rub', 0)} ₽")
    lines.append(f"Оплачено Stars: {stars_paid}")
    return "\n".join(lines)


async def notify_admin(text: str) -> None:
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception as exc:
        print("Ошибка отправки админу:", exc)


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Добро пожаловать в LiteShop.\n\nНажми кнопку ниже, чтобы открыть магазин.",
        reply_markup=main_keyboard(),
    )


@dp.message(F.web_app_data)
async def webapp_data_handler(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
    except (TypeError, json.JSONDecodeError):
        await message.answer("Не удалось обработать данные из Mini App.")
        return

    if data.get("action") != "checkout":
        await message.answer("Получены данные из Mini App.")
        return

    items = data.get("items", [])
    total_rub = float(data.get("total_rub", 0))

    if not items:
        await message.answer("Корзина пустая.")
        return

    total_stars = math.ceil(total_rub * STARS_RATE)
    user_orders[message.from_user.id] = {
        "items": items,
        "total_rub": total_rub,
        "total_stars": total_stars,
    }

    await message.answer(format_order_text(items, total_rub), reply_markup=payment_keyboard())
    await message.answer(
        f"Выбери способ оплаты.\n\nStars: {total_stars}\nКурс: {STARS_RATE} Stars = 1 ₽"
    )
    await notify_admin(format_admin_order_text(message.from_user, items, total_rub, total_stars))


@dp.message(F.text == "Оплатить Stars")
async def stars_handler(message: Message):
    order = user_orders.get(message.from_user.id)
    if not order:
        await message.answer("Сначала оформи заказ через магазин.")
        return

    items = order["items"]
    total_stars = order["total_stars"]
    item_names = ", ".join(item.get("title", "Товар") for item in items[:3])
    if len(items) > 3:
        item_names += " и другие товары"

    payload = json.dumps(
        {
            "type": "stars_order",
            "user_id": message.from_user.id,
            "items_count": len(items),
            "total_stars": total_stars,
        },
        ensure_ascii=False,
    )[:128]

    await bot.send_invoice(
        chat_id=message.chat.id,
        title="Оплата заказа LiteShop",
        description=f"Покупка: {item_names}"[:255],
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label="Заказ LiteShop", amount=total_stars)],
        provider_token="",
    )


@dp.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payment = message.successful_payment
    order = user_orders.pop(message.from_user.id, None)

    lines = ["Оплата прошла успешно.", "", f"Списано Stars: {payment.total_amount}"]
    if order:
        lines.append(f"Сумма заказа: {order['total_rub']} ₽")
    lines.extend(["", "Спасибо за покупку в LiteShop."])

    await message.answer("\n".join(lines))
    await message.answer("Можешь вернуться в магазин:", reply_markup=main_keyboard())
    await notify_admin(format_admin_paid_text(message.from_user, order, payment.total_amount))


@dp.message(F.text == "Оплатить Crypto")
async def crypto_handler(message: Message):
    order = user_orders.get(message.from_user.id)
    if not order:
        await message.answer("Сначала оформи заказ через магазин.")
        return

    await message.answer(
        "Крипто-оплата пока в режиме заглушки.\n\n"
        f"Сумма заказа: {order['total_rub']} ₽\n"
        "Следующим этапом сюда можно подключить TON или USDT."
    )


@dp.message(F.text == "В меню")
async def menu_handler(message: Message):
    await message.answer("Главное меню LiteShop", reply_markup=main_keyboard())


async def main():
    print("Бот запускается...")
    print("WEBAPP_URL =", WEBAPP_URL)
    print("STARS_RATE =", STARS_RATE)
    print("ADMIN_ID =", ADMIN_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
