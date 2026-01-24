import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import common, food_log, edit_log
from database import db
from utils import scheduler

async def main():
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
