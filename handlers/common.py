from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import re
from database import repository

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await repository.add_user(message.from_user.id)
    await message.answer(
        "Привет! Я CalorieBot. \n"
        "Просто напиши мне, что ты съел, например: 'Яблоко 150г, Творог 200г'.\n"
        "Я автоматически рассчитаю калории и сохраню их в базу."
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Команды:\n"
        "/start - Начать работу\n"
        "/database - Показать базу продуктов\n"
        "/clear - Сбросить все записи за сегодня\n"
        "/edit - Редактировать приемы пищи за сегодня\n"
        "/sync - Синхронизировать с Google Docs сейчас\n"
        "/add Название Калории - Добавить новый продукт\n"
        "/del Название - Удалить продукт из базы\n\n"
        "Просто отправь текст с едой, чтобы добавить прием пищи."
    )

@router.message(Command("database"))
async def cmd_database(message: types.Message):
    products = await repository.get_all_products()
    if not products:
        await message.answer("База данных пуста.")
        return
    
    text = "Продукты в базе:\n"
    for name, kcal in products[:70]: # Чуть больше лимит
        text += f"{name} - {kcal} ккал\n"
        
    await message.answer(text)

@router.message(Command("resetday"))
async def cmd_reset_day(message: types.Message):
    from config import USER_TZ
    from datetime import datetime
    
    user_id = message.from_user.id
    now = datetime.now(USER_TZ)
    
    await repository.delete_daily_logs(user_id, now.date())
    
    await message.answer("🔄 Все записи за сегодня удалены. Можно начинать заново!")

@router.message(Command("add"))
async def cmd_add(message: types.Message):
    text = message.text.replace("/add", "", 1).strip()
    if not text:
        await message.answer("Формат: /add Название Калории\nПример: /add Чиабатта 260")
        return
    
    # Робастный парсинг (v3)
    product_name = None
    kcal = None
    
    # 1. Ищем число перед "ккал" или "kcal"
    match_kcal = re.search(r"(\d+)\s*(?:ккал|kcal)", text, re.IGNORECASE)
    if match_kcal:
        kcal = int(match_kcal.group(1))
        product_name = text[:match_kcal.start()].strip()
    else:
        # 2. Убираем "100г/100g" и берем последнее число
        clean_text = re.sub(r"100\s*(?:г|g|мл|ml)", "", text, flags=re.IGNORECASE)
        nums = re.findall(r"(\d+)", clean_text)
        if nums:
            kcal_str = nums[-1]
            kcal = int(kcal_str)
            last_idx = clean_text.rfind(kcal_str)
            product_name = clean_text[:last_idx].strip()
            product_name = re.sub(r"\s*(?:на|в|per)\s*$", "", product_name, flags=re.IGNORECASE).strip()
            
    if not product_name or kcal is None:
        await message.answer("Не удалось распознать название или калории. Попробуйте формат: /add Чиабатта 260")
        return

    product_name = product_name.lower()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Внести", callback_data=f"save_prod:{product_name}:{kcal}"),
            InlineKeyboardButton(text="❌ Не вносить", callback_data="cancel_action")
        ]
    ])
    
    await message.answer(
        f"Внести новый продукт в базу данных?\n\n"
        f"🍎 **{product_name.capitalize()}**\n"
        f"🔥 **{kcal} ккал на 100г**",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.message(Command("del"))
async def cmd_del(message: types.Message):
    name = message.text.replace("/del", "").strip().lower()
    if not name:
        await message.answer("Формат: /del Название\nПример: /del Алча")
        return
    
    # Ищем продукт в базе для подтверждения (нечеткий поиск)
    product = await repository.get_product(name)
    if not product:
        await message.answer(f"Продукт '{name}' не найден в базе.")
        return
    
    real_name = product[1]
    kcal = product[2]
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_prod:{real_name}"),
            InlineKeyboardButton(text="↩️ Отмена", callback_data="cancel_action")
        ]
    ])
    
    await message.answer(
        f"Удалить значение из базы данных?\n\n"
        f"❌ **{real_name} — {kcal} ккал**",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("save_prod:"))
async def handle_save_prod(callback: types.CallbackQuery):
    _, name, kcal = callback.data.split(":")
    await repository.add_product(name, int(kcal), is_verified=True)
    await callback.message.edit_text(f"✅ Продукт **{name}** ({kcal} ккал) добавлен в базу!", parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data.startswith("del_prod:"))
async def handle_del_prod(callback: types.CallbackQuery):
    _, name = callback.data.split(":")
    await repository.delete_product(name)
    await callback.message.edit_text(f"🗑 Продукт **{name}** удален из базы.", parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "cancel_action")
async def handle_cancel(callback: types.CallbackQuery):
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()

@router.message(Command("clear", "resetday"))
async def cmd_clear(message: types.Message):
    from datetime import datetime
    from config import USER_TZ
    await repository.delete_daily_logs(message.from_user.id, datetime.now(USER_TZ).date())
    await message.answer("🧹 Все записи за сегодня удалены из дневника.")
@router.message(Command("sync"))
async def cmd_sync(message: types.Message):
    from utils.scheduler import sync_user_day
    from config import USER_TZ
    from datetime import datetime
    import os
    
    doc_id = os.getenv("GOOGLE_DOC_ID")
    if not doc_id:
        await message.answer("❌ GOOGLE_DOC_ID не настроен.")
        return

    # 1. Check for explicit date argument /sync DD.MM.YY
    args = message.text.replace("/sync", "").strip()
    target_date = None
    
    if args:
        try:
            # Try parsing various formats
            for fmt in ["%d.%m.%y", "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y"]:
                try:
                    target_date = datetime.strptime(args, fmt).date()
                    break
                except ValueError:
                    continue
            if not target_date:
                raise ValueError("Format unknown")
        except:
             await message.answer("⚠️ Неверный формат даты. Используйте: /sync 25.01.26")
             return
    else:
        # 2. Check last added log date
        user_id = message.from_user.id
        last_log_date = await repository.get_last_log_date(user_id)
        
        # If user has logs, use last log date. If no logs, default to today.
        if last_log_date:
            target_date = last_log_date
        else:
            target_date = datetime.now(USER_TZ).date()

    await message.answer(f"🔄 Синхронизирую данные за {target_date.strftime('%d.%m.%y')}...")
    
    try:
        success = await sync_user_day(message.from_user.id, target_date, doc_id)
        if success:
            await message.answer(f"✅ Данные за {target_date.strftime('%d.%m.%y')} успешно добавлены!")
        else:
            await message.answer(f"⚠️ Нет данных для синхронизации за {target_date.strftime('%d.%m.%y')} или произошла ошибка.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
