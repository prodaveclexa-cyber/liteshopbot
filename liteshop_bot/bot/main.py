import asyncio
import json
import math
import os
from urllib import error, request

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
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
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "https://liteshop-backend.onrender.com/api").rstrip("/")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()
ADMIN_WEB_URL = os.getenv("ADMIN_WEB_URL", "").rstrip("/")

PAYMENT_RUB_BANK = os.getenv("PAYMENT_RUB_BANK", "ЮMoney")
PAYMENT_RUB_CARD = os.getenv("PAYMENT_RUB_CARD", "2204 1201 2718 5599")
PAYMENT_RUB_RECEIVER = os.getenv("PAYMENT_RUB_RECEIVER", "Алексей")
PAYMENT_KZT_BANK = os.getenv("PAYMENT_KZT_BANK", "Alatay City Bank")
PAYMENT_KZT_CARD = os.getenv("PAYMENT_KZT_CARD", "5395 4550 1113 0349")
PAYMENT_KZT_RECEIVER = os.getenv("PAYMENT_KZT_RECEIVER", "Алексей")
PAYMENT_USDT_TRC20 = os.getenv("PAYMENT_USDT_TRC20", "TSKBVVz83xPzpHivq9Ct7UhDR8gdgYLWYD")
PAYMENT_USDT_TON = os.getenv("PAYMENT_USDT_TON", "UQDgwuttWXDJTqYzPq3X2vJEd4dzOIrHvf6zbn3D4v1HRSZM")
PAYMENT_TON = os.getenv("PAYMENT_TON", "UQBVvxAeV6jaP8K-cXEx8BNqr-Y6s4JCXpIDlBqYwjt6N")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID не найден в .env")
if not WEBAPP_URL:
    raise ValueError("WEBAPP_URL не найден в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_orders: dict[int, dict] = {}


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )


def payment_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Оплатить Stars"), KeyboardButton(text="Оплатить в рублях")],
            [KeyboardButton(text="Оплатить в тенге"), KeyboardButton(text="Оплатить криптой")],
            [KeyboardButton(text="В меню")],
        ],
        resize_keyboard=True,
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="Последние заказы")], [KeyboardButton(text="В меню")]]
    if ADMIN_WEB_URL:
        rows.insert(0, [KeyboardButton(text="Открыть админку", web_app=WebAppInfo(url=ADMIN_WEB_URL))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def api_request(path: str, method: str = "GET", payload: dict | None = None, admin: bool = False) -> dict:
    headers = {"Content-Type": "application/json"}
    if admin and ADMIN_API_KEY:
        headers["x-admin-key"] = ADMIN_API_KEY

    req = request.Request(
        url=f"{BACKEND_API_URL}{path}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(body)
            detail = parsed.get("detail") or parsed.get("error") or body
        except Exception:
            detail = body or str(exc)
        raise RuntimeError(detail) from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def format_order_text(items: list[dict], total_rub: float, order_id: str | None = None) -> str:
    lines = ["Новый заказ", ""]
    if order_id:
        lines.extend([f"Номер заказа: {order_id}", ""])
    for item in items:
        lines.append(f"• {item.get('title', 'Товар')} x{item.get('qty', 1)} — {item.get('line_total_rub', 0)} ₽")
    lines.extend(["", f"Итого: {total_rub} ₽"])
    return "\n".join(lines)


def format_admin_user(user) -> str:
    username = f"@{user.username}" if user.username else "нет username"
    return f"Пользователь: {user.full_name}\nID: {user.id}\nUsername: {username}"


def format_admin_order_text(user, order: dict, total_stars: int) -> str:
    lines = ["НОВЫЙ ЗАКАЗ", "", format_admin_user(user), ""]
    lines.append(f"Заказ: {order.get('id', order.get('order_id', 'без id'))}")
    lines.append(f"Статус: {order.get('status', 'pending')}")
    lines.extend(["", "Товары:"])
    for item in order.get("items", []):
        lines.append(
            f"• {item.get('title', 'Товар')} ({item.get('category', 'Без категории')}) "
            f"x{item.get('qty', 1)} — {item.get('line_total_rub', 0)} ₽"
        )
    lines.extend(
        [
            "",
            f"Сумма в рублях: {order.get('total_rub', 0)} ₽",
            f"Сумма в Stars: {total_stars}",
            f"Курс: {STARS_RATE} Stars = 1 ₽",
        ]
    )
    return "\n".join(lines)


def format_admin_paid_text(user, order: dict | None, stars_paid: int) -> str:
    lines = ["ОПЛАТА ПРОШЛА УСПЕШНО", "", format_admin_user(user), ""]
    if order:
        lines.append(f"Заказ: {order.get('id', order.get('order_id', 'без id'))}")
        lines.append(f"Статус: {order.get('status', 'paid')}")
        lines.extend(["", "Оплаченные товары:"])
        for item in order.get("items", []):
            lines.append(
                f"• {item.get('title', 'Товар')} ({item.get('category', 'Без категории')}) "
                f"x{item.get('qty', 1)} — {item.get('line_total_rub', 0)} ₽"
            )
        lines.extend(["", f"Сумма заказа: {order.get('total_rub', 0)} ₽"])
    lines.append(f"Оплачено Stars: {stars_paid}")
    return "\n".join(lines)


def format_recent_orders(items: list[dict]) -> str:
    if not items:
        return "Заказов пока нет."
    lines = ["Последние заказы", ""]
    for item in items:
        username = item.get("username") or "без username"
        lines.append(
            f"• {item.get('id', 'без id')} | {item.get('status', 'pending')} | "
            f"{item.get('total_rub', 0)} ₽ | {username}"
        )
    return "\n".join(lines)


def format_manual_payment_text(order: dict, method: str) -> str:
    order_id = order.get("order_id", "без id")
    total_rub = order.get("total_rub", 0)

    if method == "rub":
        return (
            f"Оплата в рублях\n\n"
            f"Номер заказа: {order_id}\n"
            f"Сумма: {total_rub} ₽\n\n"
            f"Реквизиты:\n"
            f"Банк: {PAYMENT_RUB_BANK}\n"
            f"Карта: {PAYMENT_RUB_CARD}\n"
            f"Получатель: {PAYMENT_RUB_RECEIVER}\n\n"
            f"Инструкция:\n"
            f"1. Переведи точную сумму.\n"
            f"2. Сохрани чек или скрин.\n"
            f"3. Отправь сюда скрин оплаты и номер заказа {order_id}."
        )

    if method == "kzt":
        approx_kzt = round(float(total_rub) * 6.0, 2)
        return (
            f"Оплата в тенге\n\n"
            f"Номер заказа: {order_id}\n"
            f"Сумма к оплате: {approx_kzt} ₸\n"
            f"Ориентир в рублях: {total_rub} ₽\n\n"
            f"Реквизиты:\n"
            f"Банк: {PAYMENT_KZT_BANK}\n"
            f"Карта: {PAYMENT_KZT_CARD}\n"
            f"Получатель: {PAYMENT_KZT_RECEIVER}\n\n"
            f"Инструкция:\n"
            f"1. Переведи сумму в тенге.\n"
            f"2. Сохрани чек или скрин.\n"
            f"3. Отправь сюда скрин оплаты и номер заказа {order_id}."
        )

    return (
        f"Оплата криптой\n\n"
        f"Номер заказа: {order_id}\n"
        f"Сумма заказа: {total_rub} ₽\n\n"
        f"Кошельки:\n"
        f"USDT TRC20\n{PAYMENT_USDT_TRC20}\n\n"
        f"USDT TON\n{PAYMENT_USDT_TON}\n\n"
        f"TON\n{PAYMENT_TON}\n\n"
        f"Инструкция:\n"
        f"1. Выбери подходящую сеть и кошелёк.\n"
        f"2. После перевода отправь сюда txid или скрин.\n"
        f"3. Обязательно укажи номер заказа {order_id}."
    )


async def notify_admin(text: str) -> None:
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception as exc:
        print("Ошибка отправки админу:", exc)


async def create_backend_order(message: Message, items: list[dict]) -> dict:
    payload = {
        "user_id": message.from_user.id,
        "username": message.from_user.username or "",
        "payment_method": "stars",
        "items": [{"product_id": item["product_id"], "qty": item.get("qty", 1)} for item in items],
    }
    response = await asyncio.to_thread(api_request, "/orders", "POST", payload, False)
    return response["order"]


async def set_backend_order_status(order_id: str, status: str) -> None:
    if not ADMIN_API_KEY:
        return
    await asyncio.to_thread(
        api_request,
        f"/admin/orders/{order_id}/status",
        "PUT",
        {"status": status},
        True,
    )


async def notify_manual_payment_request(user, order: dict, method: str) -> None:
    method_map = {
        "rub": "рубли",
        "kzt": "тенге",
        "crypto": "крипта",
    }
    text = (
        "ЗАПРОС НА РУЧНУЮ ОПЛАТУ\n\n"
        f"{format_admin_user(user)}\n\n"
        f"Заказ: {order.get('order_id', 'без id')}\n"
        f"Метод: {method_map.get(method, method)}\n"
        f"Сумма: {order.get('total_rub', 0)} ₽"
    )
    await notify_admin(text)


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Добро пожаловать в LiteShop.\n\nНажми кнопку ниже, чтобы открыть магазин.",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Эта команда доступна только админу.")
        return
    text = "Админ-режим открыт."
    if ADMIN_WEB_URL:
        text += "\n\nНиже можно открыть веб-админку или посмотреть последние заказы."
    await message.answer(text, reply_markup=admin_keyboard())


@dp.message(Command("orders"))
async def orders_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Эта команда доступна только админу.")
        return
    try:
        response = await asyncio.to_thread(api_request, "/admin/orders?limit=10", "GET", None, True)
        await message.answer(format_recent_orders(response.get("items", [])), reply_markup=admin_keyboard())
    except RuntimeError as exc:
        await message.answer(f"Не удалось загрузить заказы: {exc}", reply_markup=admin_keyboard())


@dp.message(Command("status"))
async def status_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Эта команда доступна только админу.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) != 3:
        await message.answer("Формат: /status <order_id> <pending|paid|processing|done|cancelled>")
        return

    _, order_id, status = parts
    try:
        await set_backend_order_status(order_id, status)
        await message.answer(f"Статус заказа {order_id} обновлён: {status}", reply_markup=admin_keyboard())
    except RuntimeError as exc:
        await message.answer(f"Не удалось обновить статус: {exc}", reply_markup=admin_keyboard())


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
    if not items:
        await message.answer("Корзина пустая.")
        return

    try:
        backend_order = await create_backend_order(message, items)
    except RuntimeError as exc:
        await message.answer(f"Не удалось создать заказ: {exc}")
        return

    total_rub = float(backend_order.get("total_rub", 0))
    total_stars = max(1, math.ceil(total_rub * STARS_RATE))

    user_orders[message.from_user.id] = {
        "order_id": backend_order["id"],
        "id": backend_order["id"],
        "items": backend_order["items"],
        "total_rub": total_rub,
        "total_stars": total_stars,
        "status": backend_order.get("status", "pending"),
    }

    await message.answer(
        format_order_text(backend_order["items"], total_rub, backend_order["id"]),
        reply_markup=payment_keyboard(),
    )
    await message.answer(
        "Выбери способ оплаты.\n\n"
        f"Stars: {total_stars}\n"
        f"Рубли: {total_rub} ₽\n"
        f"Тенге: ориентир 1 ₽ ≈ 6 ₸\n"
        "Крипта: USDT TRC20 / USDT TON / TON"
    )
    await notify_admin(format_admin_order_text(message.from_user, backend_order, total_stars))


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
            "order_id": order.get("order_id"),
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

    if order and order.get("order_id"):
        try:
            await set_backend_order_status(order["order_id"], "paid")
            order["status"] = "paid"
        except RuntimeError as exc:
            print("Не удалось обновить статус заказа:", exc)

    lines = ["Оплата прошла успешно.", "", f"Списано Stars: {payment.total_amount}"]
    if order:
        lines.append(f"Номер заказа: {order['order_id']}")
        lines.append(f"Сумма заказа: {order['total_rub']} ₽")
    lines.extend(["", "Спасибо за покупку в LiteShop."])

    await message.answer("\n".join(lines))
    await message.answer("Можешь вернуться в магазин:", reply_markup=main_keyboard())
    await notify_admin(format_admin_paid_text(message.from_user, order, payment.total_amount))


@dp.message(F.text == "Оплатить в рублях")
async def rub_handler(message: Message):
    order = user_orders.get(message.from_user.id)
    if not order:
        await message.answer("Сначала оформи заказ через магазин.")
        return
    await message.answer(format_manual_payment_text(order, "rub"))
    await notify_manual_payment_request(message.from_user, order, "rub")


@dp.message(F.text == "Оплатить в тенге")
async def kzt_handler(message: Message):
    order = user_orders.get(message.from_user.id)
    if not order:
        await message.answer("Сначала оформи заказ через магазин.")
        return
    await message.answer(format_manual_payment_text(order, "kzt"))
    await notify_manual_payment_request(message.from_user, order, "kzt")


@dp.message(F.text == "Оплатить криптой")
async def crypto_handler(message: Message):
    order = user_orders.get(message.from_user.id)
    if not order:
        await message.answer("Сначала оформи заказ через магазин.")
        return
    await message.answer(format_manual_payment_text(order, "crypto"))
    await notify_manual_payment_request(message.from_user, order, "crypto")


@dp.message(F.text == "Последние заказы")
async def latest_orders_button(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Эта кнопка доступна только админу.")
        return
    await orders_command(message)


@dp.message(F.text == "В меню")
async def menu_handler(message: Message):
    await message.answer("Главное меню LiteShop", reply_markup=main_keyboard())


async def main():
    print("Бот запускается...")
    print("WEBAPP_URL =", WEBAPP_URL)
    print("BACKEND_API_URL =", BACKEND_API_URL)
    print("ADMIN_WEB_URL =", ADMIN_WEB_URL or "not set")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())
