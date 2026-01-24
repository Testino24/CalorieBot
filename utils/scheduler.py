from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services import groq_ai as ai_service, report, google_sync
from database import db, repository
from config import USER_TZ
import aiosqlite
from datetime import datetime, timedelta
import pytz
import os

# Инициализируем планировщик с часовым поясом GMT+5
scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Yekaterinburg"))

async def verify_calories_job():
    # Helper to check products
    # In real app, we might check only old entries or unverified ones.
    print("Running weekly verification (skeleton)...")
    
    # 1. Get products
    async with aiosqlite.connect(db.DB_PATH) as conn:
        async with conn.execute("SELECT id, name, kcal_per_100g FROM products") as cursor:
            products = await cursor.fetchall()
            
    # 2. Iterate (limit for MVP/Demo)
    for pid, name, current_kcal in products[:5]: 
        print(f"Checking {name}...")
        # Check with AI
        new_kcal = await ai_service.get_calories_info(name)
        
        # 3. Compare logic
        if new_kcal > 0 and abs(new_kcal - current_kcal) > 20:
            print(f"Discrepancy for {name}: DB={current_kcal}, AI={new_kcal}")
            # Here we would notify user. For skeleton: just log or update 'last_verified'
        
        # Update last_verified
        async with aiosqlite.connect(db.DB_PATH) as conn:
             await conn.execute("UPDATE products SET last_verified = ? WHERE id = ?", (datetime.now(), pid))
             await conn.commit()

async def sync_to_google_doc_job():
    """Собирает отчет за день и отправляет в Google Doc."""
    from config import USER_TZ
    doc_id = os.getenv("GOOGLE_DOC_ID")
    if not doc_id:
        print("GOOGLE_DOC_ID not set, skipping sync.")
        return

    # 1. Получаем список всех пользователей (в MVP - одного, но сделаем правильно)
    async with aiosqlite.connect(db.DB_PATH) as conn:
        async with conn.execute("SELECT id FROM users") as cursor:
            users = await cursor.fetchall()
            print(f"DEBUG: Found {len(users)} users for sync: {users}")

    today = datetime.now(USER_TZ).date()
    
    for (user_id,) in users:
        logs = await repository.get_daily_logs(user_id, today)
        if logs:
            report_text = await report.generate_day_report(logs)
            success = await google_sync.append_to_doc(doc_id, report_text)
            if success:
                print(f"Daily sync successful for user {user_id}")
            else:
                print(f"Daily sync failed for user {user_id}")

def start_scheduler():
    scheduler.add_job(verify_calories_job, 'interval', weeks=1)
    
    # Синхронизация в конце дня (23:55)
    scheduler.add_job(sync_to_google_doc_job, 'cron', hour=23, minute=55)
    
    scheduler.start()
