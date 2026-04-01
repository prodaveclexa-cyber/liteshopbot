import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

PRODUCTS_FILE = DATA_DIR / "products.json"
ORDERS_FILE = DATA_DIR / "orders.json"
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()

DEFAULT_PRODUCTS = [
    {
        "id": "test-1-rub",
        "title": "Тестовая покупка",
        "description": "Проверочный товар для оплаты и проверки сценариев магазина.",
        "price_rub": 1.0,
        "image": "https://placehold.co/600x320/0f3d27/ffffff?text=LiteShop+Test+1+RUB",
        "banner": "https://placehold.co/1200x480/0f3d27/ffffff?text=LiteShop+Test+1+RUB",
        "category": "Тест",
        "in_stock": True,
        "sort_order": 1,
    },
    {
        "id": "chatgpt-plus-1-month",
        "title": "ChatGPT Plus на 1 месяц",
        "description": "Тестовый пример полноценного товара в каталоге.",
        "price_rub": 279.0,
        "image": "https://placehold.co/600x320/15553a/ffffff?text=ChatGPT+Plus+1+Month",
        "banner": "https://placehold.co/1200x480/15553a/ffffff?text=ChatGPT+Plus+1+Month",
        "category": "Подписки",
        "in_stock": True,
        "sort_order": 2,
    },
]

ALLOWED_ORDER_STATUSES = {"pending", "paid", "processing", "done", "cancelled"}

app = FastAPI(title="LiteShop API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        write_json(path, default)
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_files() -> None:
    products = read_json(PRODUCTS_FILE, DEFAULT_PRODUCTS)
    if not isinstance(products, list):
        products = DEFAULT_PRODUCTS.copy()

    existing_ids = {item.get("id") for item in products if isinstance(item, dict)}
    missing_defaults = [item for item in DEFAULT_PRODUCTS if item["id"] not in existing_ids]
    if missing_defaults:
        products.extend(missing_defaults)
        write_json(PRODUCTS_FILE, products)

    orders = read_json(ORDERS_FILE, [])
    if not isinstance(orders, list):
        write_json(ORDERS_FILE, [])


class ProductBase(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    price_rub: float = Field(gt=0, le=1_000_000)
    image: str = Field(default="")
    banner: str = Field(default="")
    category: str = Field(default="Без категории", max_length=80)
    in_stock: bool = True
    sort_order: int = Field(default=100, ge=0, le=100_000)

    @field_validator("title", "description", "image", "banner", "category", mode="before")
    @classmethod
    def strip_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class ProductCreate(ProductBase):
    id: Optional[str] = None


class Product(ProductBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class OrderItem(BaseModel):
    product_id: str
    qty: int = Field(default=1, ge=1, le=100)


class CreateOrderRequest(BaseModel):
    user_id: int
    username: str = ""
    items: list[OrderItem]
    payment_method: str = Field(default="stars", max_length=32)


class UpdateOrderStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


@app.on_event("startup")
def on_startup() -> None:
    ensure_files()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    return JSONResponse(status_code=500, content={"ok": False, "error": "Internal server error"})


def require_admin(x_admin_key: Optional[str]) -> None:
    if not ADMIN_API_KEY:
        return
    if x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")


def get_all_products() -> list[dict[str, Any]]:
    ensure_files()
    items = read_json(PRODUCTS_FILE, DEFAULT_PRODUCTS)
    if not isinstance(items, list):
        return DEFAULT_PRODUCTS.copy()
    return sorted(items, key=lambda item: (item.get("sort_order", 100), item.get("title", "").lower()))


def save_all_products(products: list[dict[str, Any]]) -> None:
    write_json(PRODUCTS_FILE, products)


def get_all_orders() -> list[dict[str, Any]]:
    ensure_files()
    items = read_json(ORDERS_FILE, [])
    if not isinstance(items, list):
        return []
    return sorted(items, key=lambda item: item.get("created_at", 0), reverse=True)


def save_all_orders(orders: list[dict[str, Any]]) -> None:
    write_json(ORDERS_FILE, orders)


def find_product_or_404(product_id: str) -> dict[str, Any]:
    for item in get_all_products():
        if item.get("id") == product_id:
            return item
    raise HTTPException(status_code=404, detail="Product not found")


def find_order_or_404(order_id: str) -> tuple[list[dict[str, Any]], int]:
    orders = get_all_orders()
    for index, item in enumerate(orders):
        if item.get("id") == order_id:
            return orders, index
    raise HTTPException(status_code=404, detail="Order not found")


@app.get("/api/health")
def health():
    return {"ok": True, "status": "alive", "timestamp": int(time.time())}


@app.get("/api/products")
def get_products(include_hidden: bool = False, x_admin_key: Optional[str] = Header(default=None)):
    if include_hidden:
        require_admin(x_admin_key)
    items = get_all_products()
    if not include_hidden:
        items = [item for item in items if item.get("in_stock", True)]
    return {"ok": True, "items": items, "count": len(items), "timestamp": int(time.time())}


@app.get("/api/products/{product_id}")
def get_product(product_id: str, x_admin_key: Optional[str] = Header(default=None)):
    require_admin(x_admin_key)
    return {"ok": True, "item": find_product_or_404(product_id)}


@app.post("/api/products", status_code=201)
def add_product(product: ProductCreate, x_admin_key: Optional[str] = Header(default=None)):
    require_admin(x_admin_key)
    products = get_all_products()
    product_id = product.id or str(uuid.uuid4())

    if any(item.get("id") == product_id for item in products):
        raise HTTPException(status_code=400, detail="Product with this id already exists")

    item = Product(id=product_id, **product.model_dump(exclude={"id"})).model_dump()
    products.append(item)
    save_all_products(products)
    return {"ok": True, "item": item}


@app.put("/api/products/{product_id}")
def update_product(
    product_id: str,
    product: ProductBase,
    x_admin_key: Optional[str] = Header(default=None),
):
    require_admin(x_admin_key)
    products = get_all_products()
    for index, item in enumerate(products):
        if item.get("id") == product_id:
            updated = Product(id=product_id, **product.model_dump()).model_dump()
            products[index] = updated
            save_all_products(products)
            return {"ok": True, "item": updated}
    raise HTTPException(status_code=404, detail="Product not found")


@app.delete("/api/products/{product_id}")
def delete_product(product_id: str, x_admin_key: Optional[str] = Header(default=None)):
    require_admin(x_admin_key)
    products = get_all_products()
    updated_products = [item for item in products if item.get("id") != product_id]
    if len(updated_products) == len(products):
        raise HTTPException(status_code=404, detail="Product not found")
    save_all_products(updated_products)
    return {"ok": True}


@app.get("/api/admin/summary")
def admin_summary(x_admin_key: Optional[str] = Header(default=None)):
    require_admin(x_admin_key)
    products = get_all_products()
    orders = get_all_orders()
    categories = sorted({item.get("category", "Без категории") for item in products})
    average_price = round(
        sum(float(item.get("price_rub", 0)) for item in products) / len(products), 2
    ) if products else 0
    revenue_total = round(sum(float(item.get("total_rub", 0)) for item in orders), 2)
    pending_total = sum(1 for item in orders if item.get("status") == "pending")

    return {
        "ok": True,
        "products_total": len(products),
        "categories_total": len(categories),
        "average_price_rub": average_price,
        "orders_total": len(orders),
        "orders_pending": pending_total,
        "revenue_total_rub": revenue_total,
        "categories": categories,
    }


@app.get("/api/admin/orders")
def admin_orders(limit: int = 50, x_admin_key: Optional[str] = Header(default=None)):
    require_admin(x_admin_key)
    safe_limit = max(1, min(limit, 200))
    orders = get_all_orders()[:safe_limit]
    return {"ok": True, "items": orders, "count": len(orders)}


@app.put("/api/admin/orders/{order_id}/status")
def update_order_status(
    order_id: str,
    payload: UpdateOrderStatusRequest,
    x_admin_key: Optional[str] = Header(default=None),
):
    require_admin(x_admin_key)
    if payload.status not in ALLOWED_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported order status")

    orders, index = find_order_or_404(order_id)
    orders[index]["status"] = payload.status
    orders[index]["updated_at"] = int(time.time())
    save_all_orders(orders)
    return {"ok": True, "item": orders[index]}


@app.post("/api/orders")
def create_order(order: CreateOrderRequest):
    if not order.items:
        raise HTTPException(status_code=400, detail="Order is empty")

    product_map = {item["id"]: item for item in get_all_products()}
    items_full = []
    total_rub = 0.0

    for order_item in order.items:
        product = product_map.get(order_item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product not found: {order_item.product_id}")
        if not product.get("in_stock", True):
            raise HTTPException(status_code=400, detail=f"Product is out of stock: {product['title']}")

        price = float(product["price_rub"])
        line_total = round(price * order_item.qty, 2)
        total_rub += line_total

        items_full.append(
            {
                "product_id": product["id"],
                "title": product["title"],
                "category": product.get("category", "Без категории"),
                "qty": order_item.qty,
                "price_rub": price,
                "line_total_rub": line_total,
            }
        )

    order_data = {
        "id": str(uuid.uuid4()),
        "user_id": order.user_id,
        "username": order.username,
        "payment_method": order.payment_method,
        "items": items_full,
        "total_rub": round(total_rub, 2),
        "status": "pending",
        "created_at": int(time.time()),
    }

    orders = get_all_orders()
    orders.append(order_data)
    save_all_orders(orders)

    return {"ok": True, "order": order_data}
