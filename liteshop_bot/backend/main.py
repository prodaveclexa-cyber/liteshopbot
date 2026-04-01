import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

PRODUCTS_FILE = DATA_DIR / "products.json"
ORDERS_FILE = DATA_DIR / "orders.json"

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
        "price_rub": 199.0,
        "image": "https://placehold.co/600x320/15553a/ffffff?text=ChatGPT+Plus+1+Month",
        "banner": "https://placehold.co/1200x480/15553a/ffffff?text=ChatGPT+Plus+1+Month",
        "category": "Подписки",
        "in_stock": True,
        "sort_order": 2,
    },
]


app = FastAPI(title="LiteShop API", version="1.0.0")

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


@app.on_event("startup")
def on_startup() -> None:
    ensure_files()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    return JSONResponse(status_code=500, content={"ok": False, "error": "Internal server error"})


def get_all_products() -> list[dict[str, Any]]:
    ensure_files()
    items = read_json(PRODUCTS_FILE, DEFAULT_PRODUCTS)
    if not isinstance(items, list):
        return DEFAULT_PRODUCTS.copy()
    return sorted(items, key=lambda item: (item.get("sort_order", 100), item.get("title", "").lower()))


def save_all_products(products: list[dict[str, Any]]) -> None:
    write_json(PRODUCTS_FILE, products)


def find_product_or_404(product_id: str) -> dict[str, Any]:
    for item in get_all_products():
        if item.get("id") == product_id:
            return item
    raise HTTPException(status_code=404, detail="Product not found")


@app.get("/api/health")
def health():
    return {"ok": True, "status": "alive", "timestamp": int(time.time())}


@app.get("/api/products")
def get_products(include_hidden: bool = False):
    items = get_all_products()
    if not include_hidden:
        items = [item for item in items if item.get("in_stock", True)]
    return {"ok": True, "items": items, "count": len(items), "timestamp": int(time.time())}


@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    return {"ok": True, "item": find_product_or_404(product_id)}


@app.post("/api/products", status_code=201)
def add_product(product: ProductCreate):
    products = get_all_products()
    product_id = product.id or str(uuid.uuid4())

    if any(item.get("id") == product_id for item in products):
        raise HTTPException(status_code=400, detail="Product with this id already exists")

    item = Product(id=product_id, **product.model_dump(exclude={"id"})).model_dump()
    products.append(item)
    save_all_products(products)
    return {"ok": True, "item": item}


@app.put("/api/products/{product_id}")
def update_product(product_id: str, product: ProductBase):
    products = get_all_products()
    for index, item in enumerate(products):
        if item.get("id") == product_id:
            updated = Product(id=product_id, **product.model_dump()).model_dump()
            products[index] = updated
            save_all_products(products)
            return {"ok": True, "item": updated}
    raise HTTPException(status_code=404, detail="Product not found")


@app.delete("/api/products/{product_id}")
def delete_product(product_id: str):
    products = get_all_products()
    updated_products = [item for item in products if item.get("id") != product_id]
    if len(updated_products) == len(products):
        raise HTTPException(status_code=404, detail="Product not found")
    save_all_products(updated_products)
    return {"ok": True}


@app.get("/api/admin/summary")
def admin_summary():
    products = get_all_products()
    orders = read_json(ORDERS_FILE, [])
    categories = sorted({item.get("category", "Без категории") for item in products})
    average_price = round(
        sum(float(item.get("price_rub", 0)) for item in products) / len(products), 2
    ) if products else 0

    return {
        "ok": True,
        "products_total": len(products),
        "categories_total": len(categories),
        "average_price_rub": average_price,
        "orders_total": len(orders) if isinstance(orders, list) else 0,
        "categories": categories,
    }


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

    orders = read_json(ORDERS_FILE, [])
    if not isinstance(orders, list):
        orders = []
    orders.append(order_data)
    write_json(ORDERS_FILE, orders)

    return {"ok": True, "order": order_data}
