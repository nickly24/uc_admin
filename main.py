from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import functools
import os
import threading

import telebot
from telebot import types

app = Flask(__name__)
app.secret_key = 'ucbot_secret_key_2026'  # Секретный ключ для сессий

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


def get_db_connection():
    """Создает подключение к базе данных"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Ошибка подключения к БД: {e}")
        return None


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


if __name__ == '__main__':
    threading.Thread(target=start_bot, daemon=True).start()
    app.run(debug=True, host='0.0.0.0', port=80, use_reloader=False)
