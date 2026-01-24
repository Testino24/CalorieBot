import aiosqlite
import os
import datetime
import json
from config import USER_TZ

DB_PATH = "bot_database.db"
JSON_PATH = "initial_products.json"

async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        yield db

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                created_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                kcal_per_100g INTEGER,
                last_verified TIMESTAMP,
                is_verified BOOLEAN DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS meals (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                last_report_message_id INTEGER,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                meal_id TEXT,
                timestamp TIMESTAMP,
                product_name TEXT,
                weight_g REAL,
                kcal_total REAL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(meal_id) REFERENCES meals(id)
            )
        """)
        await db.commit()
        await seed_products(db)

async def seed_products(db):
    async with db.execute("SELECT COUNT(*) FROM products") as cursor:
        count = await cursor.fetchone()
        if count[0] > 0:
            return

    if not os.path.exists(JSON_PATH):
        print(f"Warning: {JSON_PATH} not found. Seeding skipped.")
        return

    print("Seeding database from JSON...")
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        products = []
        now = datetime.datetime.now(USER_TZ)
        
        for item in data:
            products.append((item['name'], item['kcal'], now, True))
            
        await db.executemany("""
            INSERT OR IGNORE INTO products (name, kcal_per_100g, last_verified, is_verified)
            VALUES (?, ?, ?, ?)
        """, products)
        await db.commit()
        print(f"Seeded {len(products)} products from JSON.")
        
    except Exception as e:
        print(f"Error seeding database: {e}")