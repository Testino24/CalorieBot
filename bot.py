import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import common, food_log, edit_log
from database import db
from utils import scheduler
from aiohttp import web
import os

async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_health_check_server():
    app = web.Application()
    app.router.add_get('/healthz', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Health check server started on port {port}")

async def main():
    # SETUP FOR CLOUD DEPLOYMENT (Koyeb)
    # Restore files from environment variables
    if os.getenv("GOOGLE_CREDENTIALS_JSON") and not os.path.exists("credentials.json"):
        with open("credentials.json", "w", encoding="utf-8") as f:
            f.write(os.getenv("GOOGLE_CREDENTIALS_JSON"))
        print("Restored credentials.json from ENV")
        
    if os.getenv("INITIAL_PRODUCTS_JSON") and not os.path.exists("initial_products.json"):
        with open("initial_products.json", "w", encoding="utf-8") as f:
            f.write(os.getenv("INITIAL_PRODUCTS_JSON"))
        print("Restored initial_products.json from ENV")

    # Logging
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    
    # Init DB
    await db.init_db()
    
    # Bot & Dispatcher
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Include Routers
    dp.include_router(common.router)
    dp.include_router(food_log.router)
    dp.include_router(edit_log.router)
    
    # Start Scheduler
    scheduler.start_scheduler()
    
    print("Bot started...")
    # Start Health Check Server (Koyeb requirement)
    await asyncio.create_task(start_health_check_server())
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        print("Bot stopped gracefully.")

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped!")
