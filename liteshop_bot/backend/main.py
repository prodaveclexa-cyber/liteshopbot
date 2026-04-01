import json
import os
import sqlite3
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
DATABASE_FILE = DATA_DIR / "liteshop.db"
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
        "price_rub": 199.0,
        "image": "https://placehold.co/600x320/15553a/ffffff?text=ChatGPT+Plus+1+Month",
        "banner": "https://placehold.co/1200x480/15553a/ffffff?text=ChatGPT+Plus+1+Month",
        "category": "Подписки",
        "in_stock": True,
        "sort_order": 2,
    },
]

ALLOWED_ORDER_STATUSES = {"pending", "paid", "processing", "done", "cancelled"}

app = FastAPI(title="LiteShop API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price_rub REAL NOT NULL,
                image TEXT NOT NULL DEFAULT '',
                banner TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'Без категории',
                in_stock INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 100
            );

            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                payment_method TEXT NOT NULL DEFAULT 'stars',
                total_rub REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                updated_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Без категории',
                qty INTEGER NOT NULL,
                price_rub REAL NOT NULL,
                line_total_rub REAL NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_products_sort ON products(sort_order, title);
            CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
            """
        )


def migrate_products_if_needed() -> None:
    with db_connection() as conn:
        products_total = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if products_total:
            return

        json_products = read_json(PRODUCTS_FILE, DEFAULT_PRODUCTS)
        if not isinstance(json_products, list) or not json_products:
            json_products = DEFAULT_PRODUCTS

        for item in json_products:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO products (
                    id, title, description, price_rub, image, banner, category, in_stock, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.get("id")),
                    str(item.get("title", "")).strip(),
                    str(item.get("description", "")).strip(),
                    float(item.get("price_rub", 0) or 0),
                    str(item.get("image", "")).strip(),
                    str(item.get("banner", "")).strip(),
                    str(item.get("category", "Без категории")).strip() or "Без категории",
                    1 if item.get("in_stock", True) else 0,
                    int(item.get("sort_order", 100) or 100),
                ),
            )


def migrate_orders_if_needed() -> None:
    with db_connection() as conn:
        orders_total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        if orders_total:
            return

        json_orders = read_json(ORDERS_FILE, [])
        if not isinstance(json_orders, list):
            return

        for order in json_orders:
            if not isinstance(order, dict) or not order.get("id"):
                continue

            order_id = str(order.get("id"))
            conn.execute(
                """
                INSERT OR REPLACE INTO orders (
                    id, user_id, username, payment_method, total_rub, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    int(order.get("user_id", 0) or 0),
                    str(order.get("username", "")).strip(),
                    str(order.get("payment_method", "stars")).strip() or "stars",
                    float(order.get("total_rub", 0) or 0),
                    str(order.get("status", "pending")).strip() or "pending",
                    int(order.get("created_at", int(time.time())) or int(time.time())),
                    int(order.get("updated_at", 0) or 0) or None,
                ),
            )

            for item in order.get("items", []):
                if not isinstance(item, dict):
                    continue
                conn.execute(
                    """
                    INSERT INTO order_items (
                        order_id, product_id, title, category, qty, price_rub, line_total_rub
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        str(item.get("product_id", "")).strip(),
                        str(item.get("title", "")).strip(),
                        str(item.get("category", "Без категории")).strip() or "Без категории",
                        int(item.get("qty", 1) or 1),
                        float(item.get("price_rub", 0) or 0),
                        float(item.get("line_total_rub", 0) or 0),
                    ),
                )


def ensure_storage() -> None:
    init_db()
    migrate_products_if_needed()
    migrate_orders_if_needed()


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
    ensure_storage()


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


def row_to_product(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "price_rub": float(row["price_rub"]),
        "image": row["image"],
        "banner": row["banner"],
        "category": row["category"],
        "in_stock": bool(row["in_stock"]),
        "sort_order": int(row["sort_order"]),
    }


def get_all_products() -> list[dict[str, Any]]:
    ensure_storage()
    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, description, price_rub, image, banner, category, in_stock, sort_order
            FROM products
            ORDER BY sort_order ASC, LOWER(title) ASC
            """
        ).fetchall()
    return [row_to_product(row) for row in rows]


def get_product_by_id(product_id: str) -> Optional[dict[str, Any]]:
    with db_connection() as conn:
        row = conn.execute(
            """
            SELECT id, title, description, price_rub, image, banner, category, in_stock, sort_order
            FROM products
            WHERE id = ?
            """,
            (product_id,),
        ).fetchone()
    return row_to_product(row) if row else None


def upsert_product(product_id: str, payload: ProductBase | ProductCreate) -> dict[str, Any]:
    item = Product(id=product_id, **payload.model_dump(exclude={"id"})).model_dump()
    with db_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO products (
                id, title, description, price_rub, image, banner, category, in_stock, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["title"],
                item["description"],
                item["price_rub"],
                item["image"],
                item["banner"],
                item["category"],
                1 if item["in_stock"] else 0,
                item["sort_order"],
            ),
        )
    return item


def delete_product_by_id(product_id: str) -> bool:
    with db_connection() as conn:
        cursor = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    return cursor.rowcount > 0


def serialize_order(order_row: sqlite3.Row, item_rows: list[sqlite3.Row]) -> dict[str, Any]:
    payload = {
        "id": order_row["id"],
        "user_id": int(order_row["user_id"]),
        "username": order_row["username"],
        "payment_method": order_row["payment_method"],
        "total_rub": float(order_row["total_rub"]),
        "status": order_row["status"],
        "created_at": int(order_row["created_at"]),
        "items": [
            {
                "product_id": item["product_id"],
                "title": item["title"],
                "category": item["category"],
                "qty": int(item["qty"]),
                "price_rub": float(item["price_rub"]),
                "line_total_rub": float(item["line_total_rub"]),
            }
            for item in item_rows
        ],
    }
    if order_row["updated_at"] is not None:
        payload["updated_at"] = int(order_row["updated_at"])
    return payload


def get_all_orders() -> list[dict[str, Any]]:
    ensure_storage()
    with db_connection() as conn:
        order_rows = conn.execute(
            """
            SELECT id, user_id, username, payment_method, total_rub, status, created_at, updated_at
            FROM orders
            ORDER BY created_at DESC
            """
        ).fetchall()
        order_ids = [row["id"] for row in order_rows]
        if not order_ids:
            return []
        placeholders = ",".join("?" for _ in order_ids)
        item_rows = conn.execute(
            f"""
            SELECT order_id, product_id, title, category, qty, price_rub, line_total_rub
            FROM order_items
            WHERE order_id IN ({placeholders})
            ORDER BY id ASC
            """,
            order_ids,
        ).fetchall()

    items_map: dict[str, list[sqlite3.Row]] = {}
    for row in item_rows:
        items_map.setdefault(row["order_id"], []).append(row)
    return [serialize_order(row, items_map.get(row["id"], [])) for row in order_rows]


def get_order_by_id(order_id: str) -> Optional[dict[str, Any]]:
    with db_connection() as conn:
        order_row = conn.execute(
            """
            SELECT id, user_id, username, payment_method, total_rub, status, created_at, updated_at
            FROM orders
            WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        if not order_row:
            return None
        item_rows = conn.execute(
            """
            SELECT order_id, product_id, title, category, qty, price_rub, line_total_rub
            FROM order_items
            WHERE order_id = ?
            ORDER BY id ASC
            """,
            (order_id,),
        ).fetchall()
    return serialize_order(order_row, item_rows)


def update_order_status_in_db(order_id: str, status: str) -> Optional[dict[str, Any]]:
    updated_at = int(time.time())
    with db_connection() as conn:
        cursor = conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (status, updated_at, order_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_order_by_id(order_id)


def create_order_in_db(order_data: dict[str, Any]) -> dict[str, Any]:
    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO orders (
                id, user_id, username, payment_method, total_rub, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_data["id"],
                order_data["user_id"],
                order_data["username"],
                order_data["payment_method"],
                order_data["total_rub"],
                order_data["status"],
                order_data["created_at"],
                order_data.get("updated_at"),
            ),
        )
        for item in order_data["items"]:
            conn.execute(
                """
                INSERT INTO order_items (
                    order_id, product_id, title, category, qty, price_rub, line_total_rub
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_data["id"],
                    item["product_id"],
                    item["title"],
                    item["category"],
                    item["qty"],
                    item["price_rub"],
                    item["line_total_rub"],
                ),
            )
    return get_order_by_id(order_data["id"]) or order_data


def find_product_or_404(product_id: str) -> dict[str, Any]:
    item = get_product_by_id(product_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail="Product not found")


def find_order_or_404(order_id: str) -> dict[str, Any]:
    item = get_order_by_id(order_id)
    if item:
        return item
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
    product_id = product.id or str(uuid.uuid4())

    if get_product_by_id(product_id):
        raise HTTPException(status_code=400, detail="Product with this id already exists")

    item = upsert_product(product_id, product)
    return {"ok": True, "item": item}


@app.put("/api/products/{product_id}")
def update_product(
    product_id: str,
    product: ProductBase,
    x_admin_key: Optional[str] = Header(default=None),
):
    require_admin(x_admin_key)
    if not get_product_by_id(product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    updated = upsert_product(product_id, product)
    return {"ok": True, "item": updated}


@app.delete("/api/products/{product_id}")
def delete_product(product_id: str, x_admin_key: Optional[str] = Header(default=None)):
    require_admin(x_admin_key)
    if not delete_product_by_id(product_id):
        raise HTTPException(status_code=404, detail="Product not found")
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

    updated = update_order_status_in_db(order_id, payload.status)
    if not updated:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"ok": True, "item": updated}


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
        "updated_at": None,
    }

    saved_order = create_order_in_db(order_data)
    return {"ok": True, "order": saved_order}
