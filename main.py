from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Blueprint, g
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import functools
import atexit
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request

import telebot
from telebot import types

app = Flask(__name__)
app.secret_key = 'ucbot_secret_key_2026'  # Секретный ключ для сессий


def configure_logging():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv(
        "LOG_FILE", os.path.join(os.path.dirname(__file__), "app.log")
    )
    logger = logging.getLogger("ucbot")
    logger.setLevel(log_level)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [req:%(request_id)s] %(message)s"
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)

    return logger


logger = configure_logging()

BOT_TOKEN = "8331847785:AAEOrkhCGwwDPsDsodZpGOespnrNQZuJ6-8"
MINI_APP_URL = "https://nickly24-uc3-ad1c.twc1.net/"
SUPPORT_URL = "https://t.me/MISS_uc_manager"
WELCOME_TEXT = (
    "Добро пожаловать в бот пополнений MISS UC!\n"
    "Нажмите кнопку ниже, чтобы открыть мини-приложение, "
    "или обратитесь в поддержку."
)
FALLBACK_TEXT = "Пожалуйста, обратитесь в поддержку: https://t.me/MISS_uc_manager"
BANNER_PATH = os.path.join(os.path.dirname(__file__), "banner.jpg")
BOT_LOCK_PATH = os.path.join(tempfile.gettempdir(), "ucbot_telegram_bot.lock")
_bot_lock_acquired = False

REDACT_KEYS = {"token", "password", "api_key", "code", "code_text", "init_data"}
CORS_ALLOW_ORIGIN = os.getenv("CORS_ALLOW_ORIGIN", "*")
CORS_ALLOW_HEADERS = "Content-Type, X-Api-Key, X-Telegram-Init-Data"
CORS_ALLOW_METHODS = "GET, POST, OPTIONS"
FORCE_ADMIN_FALLBACK = True


def redact_payload(payload):
    if not isinstance(payload, dict):
        return payload
    redacted = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if lowered in REDACT_KEYS:
            redacted[key] = "***"
        elif lowered in {"player_id"} and isinstance(value, str):
            redacted[key] = f"{value[:2]}***{value[-2:]}" if len(value) > 4 else "***"
        elif isinstance(value, dict):
            redacted[key] = redact_payload(value)
        else:
            redacted[key] = value
    return redacted


def start_bot() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_BOT_TOKEN_HERE":
        raise ValueError("Укажите токен бота в BOT_TOKEN в admin/main.py")

    bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

    @bot.message_handler(commands=["start"])
    def handle_start(message: types.Message) -> None:
        keyboard = types.InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            types.InlineKeyboardButton(
                text="Открыть приложение",
                web_app=types.WebAppInfo(url=MINI_APP_URL),
            ),
            types.InlineKeyboardButton(text="Поддержка", url=SUPPORT_URL),
        )

        try:
            with open(BANNER_PATH, "rb") as photo:
                bot.send_photo(
                    message.chat.id,
                    photo=photo,
                    caption=WELCOME_TEXT,
                    reply_markup=keyboard,
                )
        except FileNotFoundError:
            bot.send_message(
                message.chat.id,
                WELCOME_TEXT,
                reply_markup=keyboard,
            )

    @bot.message_handler(func=lambda msg: True, content_types=["text"])
    def handle_other_messages(message: types.Message) -> None:
        if message.text and message.text.strip().startswith("/start"):
            return
        bot.send_message(message.chat.id, FALLBACK_TEXT)

    bot.infinity_polling()


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _release_bot_lock() -> None:
    global _bot_lock_acquired
    if not _bot_lock_acquired:
        return
    try:
        os.unlink(BOT_LOCK_PATH)
    except FileNotFoundError:
        pass
    _bot_lock_acquired = False


def _try_acquire_bot_lock() -> bool:
    global _bot_lock_acquired
    try:
        fd = os.open(BOT_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            with open(BOT_LOCK_PATH, "r", encoding="utf-8") as file:
                pid = int(file.read().strip() or 0)
        except (OSError, ValueError):
            pid = 0

        if _pid_is_running(pid):
            return False

        try:
            os.unlink(BOT_LOCK_PATH)
        except FileNotFoundError:
            pass
        return _try_acquire_bot_lock()

    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(str(os.getpid()))

    _bot_lock_acquired = True
    atexit.register(_release_bot_lock)
    return True


def _start_bot_thread() -> None:
    if _try_acquire_bot_lock():
        threading.Thread(target=start_bot, daemon=True).start()

# Логирование API запросов
@app.before_request
def log_request_start():
    if not request.path.startswith("/api"):
        return
    g.request_id = uuid.uuid4().hex[:12]
    g.start_time = time.time()
    payload = request.get_json(silent=True)
    logger.info(
        "API request %s %s payload=%s",
        request.method,
        request.path,
        redact_payload(payload) if payload else None,
        extra={"request_id": g.request_id},
    )


@app.after_request
def log_request_end(response):
    if not request.path.startswith("/api"):
        return response
    duration_ms = int((time.time() - g.get("start_time", time.time())) * 1000)
    logger.info(
        "API response %s %s status=%s duration=%sms",
        request.method,
        request.path,
        response.status_code,
        duration_ms,
        extra={"request_id": g.get("request_id", "-")},
    )
    return response


@app.after_request
def add_cors_headers(response):
    if request.path.startswith("/api"):
        response.headers["Access-Control-Allow-Origin"] = CORS_ALLOW_ORIGIN
        response.headers["Access-Control-Allow-Headers"] = CORS_ALLOW_HEADERS
        response.headers["Access-Control-Allow-Methods"] = CORS_ALLOW_METHODS
    return response


@app.before_request
def handle_preflight():
    if request.path.startswith("/api") and request.method == "OPTIONS":
        response = app.make_response(("", 204))
        response.headers["Access-Control-Allow-Origin"] = CORS_ALLOW_ORIGIN
        response.headers["Access-Control-Allow-Headers"] = CORS_ALLOW_HEADERS
        response.headers["Access-Control-Allow-Methods"] = CORS_ALLOW_METHODS
        return response

# Параметры подключения к БД
DB_CONFIG = {
    'host': '147.45.138.77',
    'port': 3306,
    'user': 'ucbot',
    'password': 'ucbot2026',
    'database': 'ucbot'
}

# Учетные данные для входа
ADMIN_LOGIN = 'ucbot'
ADMIN_PASSWORD = 'ucbot2026'

# Доступные значения UC
UC_VALUES = ['60 UC', '325 UC', '660 UC', '1800 UC', '3850 UC', '8100 UC']

# CodeePay
CODEEPAY_API_BASE = "https://codeepay.ru"
CODEEPAY_API_KEY = os.getenv("CODEEPAY_API_KEY", "")
SHOP_NAME = os.getenv("SHOP_NAME")
SHOP_URL = os.getenv("SHOP_URL")
PAYMENT_NOTIFY_URL = os.getenv("PAYMENT_NOTIFY_URL")

DEFAULT_VARIANTS = {
    "code": [
        {"uc_value": 60, "price": 76},
        {"uc_value": 325, "price": 374},
        {"uc_value": 660, "price": 746},
    ],
    "auto": [
        {"uc_value": 60, "price": 75},
        {"uc_value": 120, "price": 150},
        {"uc_value": 180, "price": 225},
        {"uc_value": 240, "price": 300},
        {"uc_value": 325, "price": 375},
        {"uc_value": 385, "price": 450},
        {"uc_value": 445, "price": 300},
        {"uc_value": 660, "price": 375},
        {"uc_value": 720, "price": 450},
    ],
}


def get_db_connection():
    """Создает подключение к базе данных"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Ошибка подключения к БД: {e}")
        return None


def get_env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_request_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def allow_dev_auth() -> bool:
    if not get_env_bool("ALLOW_DEV_AUTH", False):
        return False
    if get_env_bool("ALLOW_DEV_AUTH_ANY", False):
        return True
    host = (request.host or "").split(":")[0]
    return host in {"localhost", "127.0.0.1"}


def parse_init_data(init_data: str, bot_token: str):
    try:
        data = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    if "hash" not in data:
        return None

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(data.items()) if key != "hash"
    )
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if expected_hash != data.get("hash"):
        return None

    user_raw = data.get("user")
    user = json.loads(user_raw) if user_raw else {}
    return {"user": user, "auth_date": data.get("auth_date")}


def db_fetch_one(query: str, params=None):
    connection = get_db_connection()
    if not connection:
        return None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, params or ())
        row = cursor.fetchone()
        cursor.close()
        return row
    except Error as e:
        logger.error("Ошибка чтения БД: %s", e, extra={"request_id": g.get("request_id", "-")})
        return None
    finally:
        connection.close()


def db_fetch_all(query: str, params=None):
    connection = get_db_connection()
    if not connection:
        return []
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, params or ())
        rows = cursor.fetchall()
        cursor.close()
        return rows
    except Error as e:
        logger.error("Ошибка чтения БД: %s", e, extra={"request_id": g.get("request_id", "-")})
        return []
    finally:
        connection.close()


def get_or_create_user(telegram_id, username, is_admin):
    connection = get_db_connection()
    if not connection:
        return None
    try:
        cursor = connection.cursor(dictionary=True)
        if telegram_id:
            cursor.execute(
                "SELECT * FROM users WHERE telegram_id = %s", (telegram_id,)
            )
        elif username:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        if user:
            cursor.close()
            return user

        cursor.execute(
            "INSERT INTO users (telegram_id, username, is_admin) VALUES (%s, %s, %s)",
            (telegram_id, username, 1 if is_admin else 0),
        )
        connection.commit()
        user_id = cursor.lastrowid
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        return user
    except Error as e:
        logger.error("Ошибка записи пользователя: %s", e, extra={"request_id": g.get("request_id", "-")})
        return None
    finally:
        connection.close()


def get_current_user():
    init_data = request.headers.get("X-Telegram-Init-Data") or request.args.get(
        "initData"
    )
    if init_data:
        parsed = parse_init_data(init_data, BOT_TOKEN)
        if parsed and parsed.get("user"):
            user = parsed["user"]
            telegram_id = user.get("id")
            username = user.get("username") or user.get("first_name")
            return get_or_create_user(telegram_id, username, False)

    if FORCE_ADMIN_FALLBACK:
        logger.warning(
            "Admin fallback auth used",
            extra={"request_id": g.get("request_id", "-")},
        )
        return get_or_create_user(None, "admin", True)

    return None


def ensure_variant_exists(uc_value, order_type, price):
    existing = db_fetch_one(
        "SELECT id, uc_value, price FROM code_variants WHERE uc_value = %s AND purchase_type = %s",
        (uc_value, order_type),
    )
    if existing:
        return existing

    connection = get_db_connection()
    if not connection:
        return None
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO code_variants (uc_value, price, purchase_type, active) VALUES (%s, %s, %s, 1)",
            (uc_value, price, order_type),
        )
        connection.commit()
        variant_id = cursor.lastrowid
        cursor.close()
        return {"id": variant_id, "uc_value": uc_value, "price": price}
    except Error as e:
        logger.error(
            "Ошибка создания варианта: %s",
            e,
            extra={"request_id": g.get("request_id", "-")},
        )
        return None
    finally:
        connection.close()


def require_user():
    user = get_current_user()
    if not user:
        return None, (jsonify({"message": "Unauthorized"}), 401)
    return user, None


def codeepay_request(path: str, payload: dict):
    if not CODEEPAY_API_KEY:
        raise ValueError("CODEEPAY_API_KEY is not set")
    url = f"{CODEEPAY_API_BASE}{path}"
    data = json.dumps(payload).encode("utf-8")
    request_obj = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-Api-Key": CODEEPAY_API_KEY},
        method="POST",
    )
    try:
        logger.info(
            "CodeePay request %s payload=%s",
            path,
            redact_payload(payload),
            extra={"request_id": g.get("request_id", "-")},
        )
        with urllib.request.urlopen(request_obj, timeout=20) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            logger.info(
                "CodeePay response %s payload=%s",
                path,
                redact_payload(response_data),
                extra={"request_id": g.get("request_id", "-")},
            )
            return response_data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        logger.error(
            "CodeePay error %s body=%s",
            path,
            error_body,
            extra={"request_id": g.get("request_id", "-")},
        )
        raise ValueError(error_body) from e


api_bp = Blueprint("api", __name__, url_prefix="/api")


def fulfill_order(order, payment_data=None):
    connection = get_db_connection()
    if not connection:
        return False, "DB error"
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT oi.qty, cv.uc_value FROM order_items oi "
            "JOIN code_variants cv ON cv.id = oi.variant_id "
            "WHERE oi.order_id = %s",
            (order["id"],),
        )
        items = cursor.fetchall()

        for item in items:
            val_label = f"{item['uc_value']} UC"
            cursor.execute(
                "SELECT id, code FROM codes WHERE val = %s LIMIT %s",
                (val_label, item["qty"]),
            )
            codes = cursor.fetchall()
            if len(codes) < item["qty"]:
                cursor.execute(
                    "UPDATE orders SET status = %s WHERE id = %s",
                    ("failed", order["id"]),
                )
                connection.commit()
                log_operation(
                    f"Недостаточно кодов для заказа {order['id']} ({val_label})"
                )
                return False, "Not enough codes"

            for code in codes:
                if order["order_type"] == "code":
                    cursor.execute(
                        "INSERT INTO given_codes (val, code) VALUES (%s, %s)",
                        (val_label, code["code"]),
                    )
                    cursor.execute(
                        "INSERT INTO user_codes (order_id, code_id, code_value, code_text) VALUES (%s, %s, %s, %s)",
                        (order["id"], code["id"], val_label, code["code"]),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO used_codes (val, code) VALUES (%s, %s)",
                        (val_label, code["code"]),
                    )
                    cursor.execute(
                        "INSERT INTO auto_activations (order_id, player_id, status, activation_result) VALUES (%s, %s, %s, %s)",
                        (
                            order["id"],
                            order.get("player_id"),
                            "pending",
                            code["code"],
                        ),
                    )

                cursor.execute("DELETE FROM codes WHERE id = %s", (code["id"],))

            log_operation(
                f"Заказ {order['id']} оплачен, выдано кодов {item['qty']} ({val_label})"
            )

        cursor.execute(
            "UPDATE orders SET status = %s WHERE id = %s",
            ("paid", order["id"]),
        )
        connection.commit()
        return True, "OK"
    except Error as e:
        logger.error(
            "Ошибка выдачи кодов: %s",
            e,
            extra={"request_id": g.get("request_id", "-")},
        )
        return False, "Fulfillment error"
    finally:
        connection.close()


@api_bp.route("/me", methods=["GET"])
def api_me():
    user, error = require_user()
    if error:
        return error
    return jsonify(
        {
            "id": user["id"],
            "telegram_id": user.get("telegram_id"),
            "username": user.get("username"),
            "is_admin": bool(user.get("is_admin")),
        }
    )


@api_bp.route("/variants", methods=["GET"])
def api_variants():
    _, error = require_user()
    if error:
        return error

    purchase_type = request.args.get("type")
    if purchase_type not in {"code", "auto"}:
        return jsonify({"message": "Unknown type"}), 400

    rows = db_fetch_all(
        "SELECT id, uc_value, price FROM code_variants WHERE purchase_type = %s AND active = 1",
        (purchase_type,),
    )
    if not rows:
        items = DEFAULT_VARIANTS.get(purchase_type, [])
        logger.info(
            "Variants fallback type=%s count=%s",
            purchase_type,
            len(items),
            extra={"request_id": g.get("request_id", "-")},
        )
        return jsonify(
            {
                "items": [
                    {"id": idx + 1, "value": item["uc_value"], "price": item["price"]}
                    for idx, item in enumerate(items)
                ]
            }
        )

    return jsonify(
        {
            "items": [
                {"id": row["id"], "value": row["uc_value"], "price": float(row["price"])}
                for row in rows
            ]
        }
    )


@api_bp.route("/orders", methods=["POST"])
def api_orders():
    user, error = require_user()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    order_type = payload.get("type")
    items = payload.get("items") or []
    player_id = payload.get("player_id")

    if order_type not in {"code", "auto"}:
        return jsonify({"message": "Unknown order type"}), 400
    if not items:
        return jsonify({"message": "Items required"}), 400
    if order_type == "auto" and not player_id:
        return jsonify({"message": "Player ID required"}), 400

    variant_ids = [item.get("variant_id") for item in items if item.get("variant_id")]
    variant_map = {}
    if variant_ids:
        query = (
            "SELECT id, uc_value, price FROM code_variants "
            "WHERE id IN (%s) AND purchase_type = %%s AND active = 1"
            % ",".join(["%s"] * len(variant_ids))
        )
        rows = db_fetch_all(query, tuple(variant_ids) + (order_type,))
        variant_map = {row["id"]: row for row in rows}

    normalized_items = []
    total_amount = 0
    for item in items:
        qty = int(item.get("qty", 0))
        if qty <= 0:
            continue

        variant = None
        if item.get("variant_id") in variant_map:
            variant = variant_map[item["variant_id"]]
        elif item.get("uc_value") is not None:
            uc_value = int(item["uc_value"])
            variant = db_fetch_one(
                "SELECT id, uc_value, price FROM code_variants "
                "WHERE uc_value = %s AND purchase_type = %s AND active = 1",
                (uc_value, order_type),
            )
            if not variant:
                for fallback in DEFAULT_VARIANTS.get(order_type, []):
                    if fallback["uc_value"] == uc_value:
                        variant = ensure_variant_exists(
                            fallback["uc_value"], order_type, fallback["price"]
                        )
                        break

        if not variant:
            return jsonify({"message": "Unknown variant"}), 400

        line_price = float(variant["price"])
        total_amount += line_price * qty
        normalized_items.append(
            {
                "variant_id": variant["id"],
                "qty": qty,
                "price": line_price,
            }
        )

    if not normalized_items:
        return jsonify({"message": "No valid items"}), 400

    connection = get_db_connection()
    if not connection:
        return jsonify({"message": "DB error"}), 500
    try:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO orders (user_id, order_type, amount, player_id) VALUES (%s, %s, %s, %s)",
            (user["id"], order_type, total_amount, player_id),
        )
        order_id = cursor.lastrowid

        for item in normalized_items:
            cursor.execute(
                "INSERT INTO order_items (order_id, variant_id, qty, price_at_purchase) VALUES (%s, %s, %s, %s)",
                (order_id, item["variant_id"], item["qty"], item["price"]),
            )

        connection.commit()
        cursor.close()
        logger.info(
            "Order created id=%s type=%s amount=%s",
            order_id,
            order_type,
            total_amount,
            extra={"request_id": g.get("request_id", "-")},
        )
        return jsonify({"order_id": order_id, "amount": total_amount})
    except Error as e:
        logger.error(
            "Ошибка создания заказа: %s",
            e,
            extra={"request_id": g.get("request_id", "-")},
        )
        return jsonify({"message": "Order create failed"}), 500
    finally:
        connection.close()


@api_bp.route("/orders/confirm", methods=["POST"])
def api_orders_confirm():
    _, error = require_user()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    order_id = payload.get("order_id")
    if not order_id:
        return jsonify({"message": "order_id required"}), 400

    order = db_fetch_one("SELECT * FROM orders WHERE id = %s", (order_id,))
    if not order:
        return jsonify({"message": "Order not found"}), 404

    if order.get("status") == "paid":
        ok, message = fulfill_order(order)
        return jsonify({"message": message, "fulfilled": ok})

    if not order.get("payment_order_id"):
        return jsonify({"message": "Payment not initialized"}), 400

    try:
        payment_data = codeepay_request(
            "/get_payment", {"order_id": order["payment_order_id"]}
        )
    except ValueError as e:
        return jsonify({"message": "CodeePay error", "details": str(e)}), 502

    paid = payment_data.get("payment_status") == "paid" or payment_data.get(
        "payment_deposited"
    )
    if not paid:
        return jsonify({"message": "Not paid yet"}), 200

    ok, message = fulfill_order(order, payment_data)
    return jsonify({"message": message, "fulfilled": ok})


@api_bp.route("/payment/create", methods=["POST"])
def api_payment_create():
    user, error = require_user()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    order_id = payload.get("order_id")
    method_slug = payload.get("method_slug", "sbp")
    if not order_id:
        return jsonify({"message": "order_id required"}), 400
    if method_slug not in {"sbp", "card"}:
        return jsonify({"message": "Invalid method"}), 400

    order = db_fetch_one("SELECT * FROM orders WHERE id = %s", (order_id,))
    if not order:
        return jsonify({"message": "Order not found"}), 404

    notify_url = PAYMENT_NOTIFY_URL
    if not notify_url:
        return jsonify({"message": "PAYMENT_NOTIFY_URL is not set"}), 500

    request_payload = {
        "method_slug": method_slug,
        "amount": float(order["amount"]),
        "description": f"Заказ #{order_id}",
        "shop_name": SHOP_NAME,
        "shop_url": SHOP_URL,
        "metadata": {
            "order_id": order_id,
            "notification_url": notify_url,
            "user_id": user["id"],
        },
    }

    try:
        response_data = codeepay_request("/initiate_payment", request_payload)
    except ValueError as e:
        return jsonify({"message": "CodeePay error", "details": str(e)}), 502
    payment_url = response_data.get("url")
    payment_order_id = response_data.get("order_id")

    connection = get_db_connection()
    if not connection:
        return jsonify({"message": "DB error"}), 500
    try:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE orders SET payment_provider = %s, payment_order_id = %s, payment_method = %s, payment_url = %s WHERE id = %s",
            ("codeepay", payment_order_id, method_slug, payment_url, order_id),
        )
        connection.commit()
        cursor.close()
    except Error as e:
        print(f"Ошибка обновления заказа: {e}")
    finally:
        connection.close()

    logger.info(
        "Payment created order_id=%s payment_order_id=%s method=%s",
        order_id,
        payment_order_id,
        method_slug,
        extra={"request_id": g.get("request_id", "-")},
    )
    return jsonify({"url": payment_url, "order_id": order_id})


@api_bp.route("/payment/status", methods=["POST"])
def api_payment_status():
    _, error = require_user()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    order_id = payload.get("order_id")
    if not order_id:
        return jsonify({"message": "order_id required"}), 400

    order = db_fetch_one("SELECT * FROM orders WHERE id = %s", (order_id,))
    if not order or not order.get("payment_order_id"):
        return jsonify({"message": "Payment not initialized"}), 404

    try:
        response_data = codeepay_request(
            "/get_payment", {"order_id": order["payment_order_id"]}
        )
        return jsonify(response_data)
    except ValueError as e:
        return jsonify({"message": "CodeePay error", "details": str(e)}), 502


@api_bp.route("/payment/callback", methods=["POST"])
def api_payment_callback():
    allowed_ip = "82.97.245.146"
    if get_request_ip() != allowed_ip and not get_env_bool("ALLOW_WEBHOOK_ANY", False):
        return jsonify({"message": "Forbidden"}), 403

    data = request.get_json(silent=True) or {}
    logger.info(
        "Webhook received payload=%s",
        redact_payload(data),
        extra={"request_id": g.get("request_id", "-")},
    )
    payment_order_id = data.get("payment_order_id")
    payment_status = (data.get("payment_status") or "").lower()
    payment_deposited = bool(data.get("payment_deposited"))
    payment_method = data.get("payment_method")
    payment_id = data.get("payment_id")
    payment_metadata = data.get("payment_metadata") or {}
    order_id = payment_metadata.get("order_id")

    order = None
    if payment_order_id:
        order = db_fetch_one(
            "SELECT * FROM orders WHERE payment_order_id = %s", (payment_order_id,)
        )
    if not order and order_id:
        order = db_fetch_one("SELECT * FROM orders WHERE id = %s", (order_id,))

    if not order:
        logger.warning(
            "Webhook order not found payment_order_id=%s order_id=%s",
            payment_order_id,
            order_id,
            extra={"request_id": g.get("request_id", "-")},
        )
        return jsonify({"message": "Order not found"}), 200

    paid = payment_deposited or payment_status in {"paid", "success", "completed"}

    if paid:
        connection = get_db_connection()
        if not connection:
            return jsonify({"message": "DB error"}), 500
        try:
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE orders SET status = %s, payment_id = %s, payment_method = %s WHERE id = %s",
                ("paid", payment_id, payment_method, order["id"]),
            )
            connection.commit()
            cursor.close()
        except Error as e:
            logger.error(
                "Ошибка обновления заказа: %s",
                e,
                extra={"request_id": g.get("request_id", "-")},
            )
        finally:
            connection.close()

        ok, message = fulfill_order(order, data)
        if ok:
            logger.info(
                "Order fulfilled id=%s",
                order["id"],
                extra={"request_id": g.get("request_id", "-")},
            )
        else:
            logger.warning(
                "Order fulfill failed id=%s reason=%s",
                order["id"],
                message,
                extra={"request_id": g.get("request_id", "-")},
            )
    else:
        connection = get_db_connection()
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute(
                    "UPDATE orders SET status = %s WHERE id = %s",
                    ("failed", order["id"]),
                )
                connection.commit()
                cursor.close()
            except Error as e:
                logger.error(
                    "Ошибка обновления заказа: %s",
                    e,
                    extra={"request_id": g.get("request_id", "-")},
                )
            finally:
                connection.close()
        logger.info(
            "Order failed id=%s status=%s",
            order["id"],
            payment_status,
            extra={"request_id": g.get("request_id", "-")},
        )

    return jsonify({"message": "OK"}), 200


@api_bp.route("/my-codes", methods=["GET"])
def api_my_codes():
    user, error = require_user()
    if error:
        return error

    rows = db_fetch_all(
        "SELECT id, code_value, code_text, used, delivered_at FROM user_codes WHERE order_id IN "
        "(SELECT id FROM orders WHERE user_id = %s) ORDER BY delivered_at DESC",
        (user["id"],),
    )
    items = [
        {
            "id": row["id"],
            "value": int(str(row["code_value"]).split()[0]),
            "code": row["code_text"],
            "used": bool(row["used"]),
            "date": row["delivered_at"].strftime("%d.%m.%Y") if row["delivered_at"] else "",
        }
        for row in rows
    ]
    return jsonify({"items": items})


@api_bp.route("/availability", methods=["POST"])
def api_availability():
    _, error = require_user()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    uc_value = payload.get("uc_value")
    qty = int(payload.get("qty", 0))
    if not uc_value or qty <= 0:
        return jsonify({"message": "Invalid request"}), 400

    val_label = f"{int(uc_value)} UC"
    row = db_fetch_one(
        "SELECT COUNT(*) AS total FROM codes WHERE val = %s",
        (val_label,),
    )
    total = int(row["total"]) if row else 0
    available = total >= qty
    return jsonify({"available": available, "available_count": total})


@api_bp.route("/<path:subpath>", methods=["OPTIONS"])
def api_options(subpath):
    response = app.make_response(("", 204))
    response.headers["Access-Control-Allow-Origin"] = CORS_ALLOW_ORIGIN
    response.headers["Access-Control-Allow-Headers"] = CORS_ALLOW_HEADERS
    response.headers["Access-Control-Allow-Methods"] = CORS_ALLOW_METHODS
    return response


def log_operation(text):
    """Записывает операцию в историю"""
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            query = "INSERT INTO operation_history (text) VALUES (%s)"
            cursor.execute(query, (text,))
            connection.commit()
            cursor.close()
        except Error as e:
            print(f"Ошибка записи в историю: {e}")
        finally:
            connection.close()


def login_required(f):
    """Декоратор для проверки авторизации"""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_LOGIN and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            log_operation(f"Вход в админку: {username} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            return redirect(url_for('index'))
        else:
            flash('Неверный логин или пароль', 'error')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    """Выход из системы"""
    log_operation(f"Выход из админки - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    """Главная страница админки"""
    return render_template('index.html')


@app.route('/codes')
@login_required
def codes():
    """Просмотр кодов из таблицы codes"""
    table = request.args.get('table', 'codes')
    connection = get_db_connection()
    
    if not connection:
        flash('Ошибка подключения к базе данных', 'error')
        return render_template('codes.html', codes=[], table=table)
    
    try:
        cursor = connection.cursor(dictionary=True)
        query = f"SELECT * FROM {table} ORDER BY id DESC"
        cursor.execute(query)
        codes_list = cursor.fetchall()
        cursor.close()
        
        return render_template('codes.html', codes=codes_list, table=table, uc_values=UC_VALUES)
    except Error as e:
        flash(f'Ошибка получения данных: {e}', 'error')
        return render_template('codes.html', codes=[], table=table)
    finally:
        connection.close()


@app.route('/codes/add', methods=['GET', 'POST'])
@login_required
def add_code():
    """Добавление нового кода"""
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        val = request.form.get('val', '').strip()
        table = request.form.get('table', 'codes')
        
        if not code:
            flash('Код не может быть пустым', 'error')
            return redirect(url_for('add_code', table=table))
        
        if not val or val not in UC_VALUES:
            flash('Необходимо выбрать значение UC', 'error')
            return redirect(url_for('add_code', table=table))
        
        connection = get_db_connection()
        if not connection:
            flash('Ошибка подключения к базе данных', 'error')
            return redirect(url_for('add_code', table=table))
        
        try:
            cursor = connection.cursor()
            query = f"INSERT INTO {table} (val, code) VALUES (%s, %s)"
            cursor.execute(query, (val, code))
            
            connection.commit()
            code_id = cursor.lastrowid
            cursor.close()
            
            log_operation(f"Добавлен код ID {code_id} в таблицу {table}: {val} - {code}")
            flash('Код успешно добавлен', 'success')
            return redirect(url_for('codes', table=table))
        except Error as e:
            flash(f'Ошибка добавления кода: {e}', 'error')
        finally:
            connection.close()
    
    table = request.args.get('table', 'codes')
    return render_template('add_code.html', table=table, uc_values=UC_VALUES)


@app.route('/codes/edit/<int:code_id>', methods=['GET', 'POST'])
@login_required
def edit_code(code_id):
    """Редактирование кода"""
    table = request.args.get('table', 'codes')
    connection = get_db_connection()
    
    if not connection:
        flash('Ошибка подключения к базе данных', 'error')
        return redirect(url_for('codes', table=table))
    
    if request.method == 'POST':
        new_code = request.form.get('code', '').strip()
        new_val = request.form.get('val', '').strip()
        
        if not new_code:
            flash('Код не может быть пустым', 'error')
            return redirect(url_for('edit_code', code_id=code_id, table=table))
        
        if not new_val or new_val not in UC_VALUES:
            flash('Необходимо выбрать значение UC', 'error')
            return redirect(url_for('edit_code', code_id=code_id, table=table))
        
        try:
            cursor = connection.cursor(dictionary=True)
            # Получаем старый код для истории
            cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (code_id,))
            old_code_data = cursor.fetchone()
            
            # Обновляем код и val
            query = f"UPDATE {table} SET val = %s, code = %s WHERE id = %s"
            cursor.execute(query, (new_val, new_code, code_id))
            
            connection.commit()
            cursor.close()
            
            log_operation(f"Изменен код ID {code_id} в таблице {table}: {old_code_data.get('val')} {old_code_data.get('code')} -> {new_val} {new_code}")
            flash('Код успешно изменен', 'success')
            return redirect(url_for('codes', table=table))
        except Error as e:
            flash(f'Ошибка изменения кода: {e}', 'error')
        finally:
            connection.close()
    
    # GET запрос - показываем форму редактирования
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (code_id,))
        code_data = cursor.fetchone()
        cursor.close()
        
        if not code_data:
            flash('Код не найден', 'error')
            return redirect(url_for('codes', table=table))
        
        return render_template('edit_code.html', code=code_data, table=table, uc_values=UC_VALUES)
    except Error as e:
        flash(f'Ошибка получения данных: {e}', 'error')
        return redirect(url_for('codes', table=table))
    finally:
        connection.close()


@app.route('/codes/delete/<int:code_id>', methods=['POST'])
@login_required
def delete_code(code_id):
    """Удаление кода"""
    table = request.args.get('table', 'codes')
    connection = get_db_connection()
    
    if not connection:
        return jsonify({'success': False, 'message': 'Ошибка подключения к базе данных'})
    
    try:
        cursor = connection.cursor(dictionary=True)
        # Получаем код для истории
        cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (code_id,))
        code_data = cursor.fetchone()
        
        if code_data:
            val_value = code_data.get('val', 'N/A')
            code_value = code_data.get('code', 'N/A')
            log_text = f"Удален код ID {code_id} из таблицы {table}: {val_value} - {code_value}"
        else:
            log_text = f"Удален код ID {code_id} из таблицы {table}"
        
        # Удаляем код
        cursor.execute(f"DELETE FROM {table} WHERE id = %s", (code_id,))
        connection.commit()
        cursor.close()
        
        log_operation(log_text)
        return jsonify({'success': True, 'message': 'Код успешно удален'})
    except Error as e:
        return jsonify({'success': False, 'message': f'Ошибка удаления: {e}'})
    finally:
        connection.close()


@app.route('/codes/move', methods=['POST'])
@login_required
def move_code():
    """Перенос кода между таблицами"""
    code_id = request.form.get('code_id')
    from_table = request.form.get('from_table')
    to_table = request.form.get('to_table')
    
    if not all([code_id, from_table, to_table]):
        return jsonify({'success': False, 'message': 'Не все параметры указаны'})
    
    connection = get_db_connection()
    if not connection:
        return jsonify({'success': False, 'message': 'Ошибка подключения к базе данных'})
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Получаем данные кода
        cursor.execute(f"SELECT * FROM {from_table} WHERE id = %s", (code_id,))
        code_data = cursor.fetchone()
        
        if not code_data:
            return jsonify({'success': False, 'message': 'Код не найден'})
        
        # Получаем val и code
        val_value = code_data.get('val')
        code_value = code_data.get('code')
        
        # Вставляем в новую таблицу
        insert_query = f"INSERT INTO {to_table} (val, code) VALUES (%s, %s)"
        cursor.execute(insert_query, (val_value, code_value))
        
        # Удаляем из старой таблицы
        cursor.execute(f"DELETE FROM {from_table} WHERE id = %s", (code_id,))
        
        connection.commit()
        cursor.close()
        
        log_operation(f"Перенесен код ID {code_id} из {from_table} в {to_table}: {val_value} - {code_value}")
        return jsonify({'success': True, 'message': 'Код успешно перенесен'})
    except Error as e:
        return jsonify({'success': False, 'message': f'Ошибка переноса: {e}'})
    finally:
        connection.close()


@app.route('/history')
@login_required
def history():
    """Просмотр истории операций"""
    connection = get_db_connection()
    
    if not connection:
        flash('Ошибка подключения к базе данных', 'error')
        return render_template('history.html', operations=[])
    
    try:
        cursor = connection.cursor(dictionary=True)
        query = "SELECT * FROM operation_history ORDER BY created_at DESC LIMIT 1000"
        cursor.execute(query)
        operations = cursor.fetchall()
        cursor.close()
        
        return render_template('history.html', operations=operations)
    except Error as e:
        flash(f'Ошибка получения данных: {e}', 'error')
        return render_template('history.html', operations=[])
    finally:
        connection.close()


app.register_blueprint(api_bp)
_start_bot_thread()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80, use_reloader=False)
