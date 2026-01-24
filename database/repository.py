import aiosqlite
import datetime
import logging
import json
import os
from .db import DB_PATH, JSON_PATH
from config import USER_TZ

async def add_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.datetime.now(USER_TZ)
        await db.execute("INSERT OR IGNORE INTO users (id, created_at) VALUES (?, ?)", (user_id, now))
        await db.commit()

async def get_product(name):
    async with aiosqlite.connect(DB_PATH) as db:
        name_lower = name.lower().strip()
        
        # Функция для нормализации (сортировки слов)
        def normalize_name(n):
            return " ".join(sorted(n.split()))

        target_norm = normalize_name(name_lower)

        # 1. Сначала ищем точное совпадение
        async with db.execute("SELECT * FROM products WHERE name = ?", (name_lower,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row
        
        # 2. Поиск по нормализованным словам (защита от перестановки)
        # Получаем все продукты и ищем совпадение по отсортированным словам
        async with db.execute("SELECT * FROM products") as cursor:
            async for row in cursor:
                db_name_norm = normalize_name(row[1]) # row[1] это name
                if db_name_norm == target_norm:
                    logging.info(f"MATCH (Normalized): '{name_lower}' -> '{row[1]}'")
                    return row

        # 3. Нечеткий поиск (LIKE) если точного по словам нет
        async with db.execute("""
            SELECT * FROM products 
            WHERE ? LIKE '%' || name || '%' 
               OR name LIKE '%' || ? || '%'
            ORDER BY length(name) ASC
            LIMIT 1
        """, (name_lower, name_lower)) as cursor:
            return await cursor.fetchone()

async def add_product(name, kcal, is_verified=True):
    name = name.lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.datetime.now(USER_TZ)
        await db.execute("""
            INSERT OR REPLACE INTO products (name, kcal_per_100g, last_verified, is_verified)
            VALUES (?, ?, ?, ?)
        """, (name, kcal, now, is_verified))
        await db.commit()
    
    # Sync to JSON
    await sync_product_to_json(name, kcal, action="add")

async def sync_product_to_json(name, kcal=None, action="add"):
    """Синхронизирует изменения с JSON файлом (Золотой стандарт)"""
    try:
        data = []
        if os.path.exists(JSON_PATH):
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        
        if action == "add":
            # Удаляем старый если есть, и добавляем новый
            data = [p for p in data if p['name'] != name]
            data.append({"name": name, "kcal": int(kcal)})
        elif action == "delete":
            data = [p for p in data if p['name'] != name]
            
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logging.info(f"JSON synced: {action} {name}")
    except Exception as e:
        logging.error(f"Error syncing to JSON: {e}")

async def create_meal(meal_id, user_id, message_id=None, timestamp=None):
    async with aiosqlite.connect(DB_PATH) as db:
        now = timestamp if timestamp else datetime.datetime.now(USER_TZ)
        await db.execute("INSERT INTO meals (id, user_id, last_report_message_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (meal_id, user_id, message_id, now, now))
        await db.commit()

async def update_meal_report_id(meal_id, message_id):
     async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE meals SET last_report_message_id = ? WHERE id = ?", (message_id, meal_id))
        await db.commit()

async def get_last_meal(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        # Get the most recent meal
        async with db.execute("""
            SELECT * FROM meals 
            WHERE user_id = ? 
            ORDER BY created_at DESC 
            LIMIT 1
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row
            return None

async def update_meal_time(meal_id):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.datetime.now(USER_TZ)
        await db.execute("UPDATE meals SET updated_at = ? WHERE id = ?", (now, meal_id))
        await db.commit()

async def add_log(user_id, meal_id, product_name, weight, kcal, timestamp=None):
    async with aiosqlite.connect(DB_PATH) as db:
        now = timestamp if timestamp else datetime.datetime.now(USER_TZ)
        await db.execute("""
            INSERT INTO daily_logs (user_id, meal_id, product_name, weight_g, kcal_total, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, meal_id, product_name, weight, kcal, now))
        await db.commit()

async def get_daily_logs(user_id, date: datetime.date):
    date_str = date.strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, meal_id, timestamp, product_name, weight_g, kcal_total 
            FROM daily_logs 
            WHERE user_id = ? AND substr(timestamp, 1, 10) = ?
            ORDER BY timestamp ASC
        """, (user_id, date_str)) as cursor:
            return await cursor.fetchall()

async def get_all_products():
     async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, kcal_per_100g FROM products ORDER BY name") as cursor:
            return await cursor.fetchall()

async def delete_daily_logs(user_id, date: datetime.date):
    date_str = date.strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            DELETE FROM daily_logs 
            WHERE user_id = ? AND substr(timestamp, 1, 10) = ?
        """, (user_id, date_str))
        
        await db.execute("""
            DELETE FROM meals 
            WHERE user_id = ? AND substr(created_at, 1, 10) = ?
        """, (user_id, date_str))
        
        await db.commit()

async def delete_product(name):
    name_clean = name.lower().strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM products WHERE name = ?", (name_clean,))
        await db.commit()
    
    # Sync to JSON
    await sync_product_to_json(name_clean, action="delete")

async def delete_meal_at_timestamp(user_id, timestamp):
    """Удаляет существующие записи за конкретный момент времени для перезаписи."""
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Находим meal_id за это время
        async with db.execute("SELECT id FROM meals WHERE user_id = ? AND created_at = ?", (user_id, timestamp)) as cursor:
            rows = await cursor.fetchall()
            meal_ids = [r[0] for r in rows]
        
        if meal_ids:
            # 2. Удаляем логи
            placeholders = ",".join(["?"] * len(meal_ids))
            await db.execute(f"DELETE FROM daily_logs WHERE meal_id IN ({placeholders})", meal_ids)
            # 3. Удаляем сами приемы пищи
            await db.execute(f"DELETE FROM meals WHERE id IN ({placeholders})", meal_ids)
            await db.commit()
            logging.info(f"Overwriting: Deleted {len(meal_ids)} older meals at {timestamp}")

async def get_log_entry(log_id):
    """Получает одну запись из логов по ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, product_name, weight_g, kcal_total, meal_id FROM daily_logs WHERE id = ?", (log_id,)) as cursor:
            return await cursor.fetchone()

async def update_log_entry(log_id, weight=None, kcal=None):
    """Обновляет вес или калории конкретной записи."""
    async with aiosqlite.connect(DB_PATH) as db:
        if weight is not None and kcal is not None:
            await db.execute("UPDATE daily_logs SET weight_g = ?, kcal_total = ? WHERE id = ?", (weight, kcal, log_id))
        elif weight is not None:
            await db.execute("UPDATE daily_logs SET weight_g = ? WHERE id = ?", (weight, log_id))
        elif kcal is not None:
            await db.execute("UPDATE daily_logs SET kcal_total = ? WHERE id = ?", (kcal, log_id))
        await db.commit()

async def delete_log_entry(log_id):
    """Удаляет конкретную запись из логов."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM daily_logs WHERE id = ?", (log_id,))
        await db.commit()
