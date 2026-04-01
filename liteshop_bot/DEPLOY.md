# LiteShop: как опубликовать проект

Ниже самый простой путь, чтобы магазин начал открываться из Telegram и показывать реальные товары.

## 1. Опубликуй backend

Самый простой вариант: `Render`.

Что нужно сделать:

1. Создай аккаунт на Render.
2. Создай новый `Web Service`.
3. Загрузи туда проект или подключи GitHub-репозиторий.
4. Для сервиса backend укажи:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port 10000`
5. После запуска Render выдаст адрес вида:
   - `https://my-liteshop-api.onrender.com`

Проверь:

- `https://my-liteshop-api.onrender.com/api/health`
- `https://my-liteshop-api.onrender.com/api/products`

Если всё хорошо, backend готов.

## 2. Подставь адрес backend в витрину и админку

Открой файл:

- `webapp/config.js`
- `admin/config.js`

И замени строку:

```js
API_BASE_URL: "https://your-backend-domain.onrender.com/api"
```

На реальный адрес, например:

```js
API_BASE_URL: "https://my-liteshop-api.onrender.com/api"
```

## 3. Опубликуй магазин и админку

Самый простой вариант: `Netlify`.

### Магазин

1. Создай отдельный сайт в Netlify из папки `webapp`.
2. После публикации получишь адрес вида:
   - `https://my-liteshop.netlify.app`

### Админка

1. Создай второй сайт в Netlify из папки `admin`.
2. После публикации получишь адрес вида:
   - `https://my-liteshop-admin.netlify.app`

## 4. Пропиши адрес магазина в боте

Открой `.env` и замени:

```env
WEBAPP_URL=https://heartfelt-twilight-4c9b6e.netlify.app
```

На новый адрес магазина, например:

```env
WEBAPP_URL=https://my-liteshop.netlify.app
```

После этого перезапусти бота.

## 5. Как запускать локально

Когда Python будет установлен, локальный запуск такой:

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
python bot/main.py
```

## 6. Почему раньше не было тестового товара

Потому что:

- бот открывал старую опубликованную витрину;
- витрина обращалась к `http://127.0.0.1:8000/api`;
- в Telegram такой адрес не ведёт на твой компьютер.

Теперь это исправлено через отдельные файлы настройки:

- `webapp/config.js`
- `admin/config.js`

Достаточно поменять адрес backend в этих двух файлах и заново опубликовать сайты.
