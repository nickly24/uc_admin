# Админка UC Bot

Flask приложение для управления кодами в базе данных MySQL.

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Создайте таблицу истории операций в базе данных:
```bash
mysql -u ucbot -p'ucbot2026' -h 147.45.138.77 -P 3306 -D ucbot < create_history_table.sql
```

## Запуск

```bash
python app.py
```

Приложение будет доступно по адресу: http://localhost:5000

## Авторизация

- Логин: `ucbot`
- Пароль: `ucbot2026`

## Функционал

- Просмотр кодов из всех таблиц (codes, used_codes, given_codes)
- Добавление новых кодов
- Редактирование кодов
- Удаление кодов
- Перенос кодов между таблицами
- Просмотр истории операций (только чтение)

## Структура проекта

```
admin/
├── app.py                 # Основное Flask приложение
├── requirements.txt       # Зависимости Python
├── create_history_table.sql  # SQL скрипт для создания таблицы истории
├── templates/            # HTML шаблоны
│   ├── base.html
│   ├── login.html
│   ├── index.html
│   ├── codes.html
│   ├── add_code.html
│   ├── edit_code.html
│   └── history.html
└── static/
    └── css/
        └── style.css     # Стили
```
# uc_admin
