import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env")
# GROQ_API_KEY будет проверяться при импорте groq_ai
# if not GROQ_API_KEY:
#     raise ValueError("GROQ_API_KEY is not set in .env")

from datetime import timezone, timedelta

# Настройка твоего часового пояса (GMT+5)
USER_TZ = timezone(timedelta(hours=5))