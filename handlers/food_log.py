from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import repository
from services import groq_ai as ai_service, report
from config import USER_TZ
import uuid
from datetime import datetime
import logging
import re

router = Router()

class FoodLogState(StatesGroup):
    waiting_for_action = State()
    waiting_for_kcal = State() # Для интерактивного опроса
    waiting_for_date = State() # Для ввода даты при "Другом дне"

@router.message(F.text & ~F.text.startswith('/'), StateFilter(None))
async def handle_food_text(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    text = message.text
    
    # 0. Перехват: Если в тексте уже есть дата или время, мы считаем это историческим логом
    # и пропускаем вопрос про "Добавить к текущему".
    # Паттерны для даты (dd/mm/yy) и времени (hh:mm)
    has_date = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", text)
    has_time = re.search(r"\d{1,2}:\d{2}", text)
    
    if has_date or has_time:
        await unified_process_input(message, text, user_id, is_new_meal=True, state=state)
        return

    # 1. Check last meal context (if within 60 mins)
    last_meal = await repository.get_last_meal(user_id)
    
    should_prompt = False
    if last_meal:
        meal_id, uid, msg_id, created_at, updated_at = last_meal
        
        if isinstance(updated_at, str):
            try:
                last_time = datetime.strptime(updated_at.split('.')[0], "%Y-%m-%d %H:%M:%S")
                last_time = last_time.replace(tzinfo=USER_TZ)
            except:
                last_time = datetime.now(USER_TZ)
        else:
            last_time = updated_at
            
        now = datetime.now(USER_TZ)
        diff = (now - last_time).total_seconds() / 60
        
        if diff < 60:
            should_prompt = True
    
    if should_prompt:
        await state.update_data(text=text, meal_id=last_meal[0])
        await state.set_state(FoodLogState.waiting_for_action)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить в текущий", callback_data="add_current")],
            [InlineKeyboardButton(text="🆕 Новый прием", callback_data="new_meal")],
            [InlineKeyboardButton(text="📅 Данные за другой день", callback_data="other_day")]
        ])
        await message.answer("Прошло менее 60 минут. Добавить к предыдущему приему?", reply_markup=kb)
    else:
        await unified_process_input(message, text, user_id, is_new_meal=True, state=state)

@router.callback_query(FoodLogState.waiting_for_action)
async def handle_action(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    text = data.get('text')
    meal_id = data.get('meal_id')
    
    action = callback.data
    await state.clear()
    
    if action == "other_day":
        # Переходим в режим ожидания даты
        await state.update_data(text=text) # Сохраняем текст еды
        await state.set_state(FoodLogState.waiting_for_date)
        await callback.message.answer("📅 За какое число этот прием пищи?\nНапишите дату (например: 21.01) или 'вчера', 'позавчера'.")
    else:
        is_new = (action == "new_meal")
        actual_meal_id = meal_id if not is_new else None
        await state.clear()
        await unified_process_input(callback.message, text, callback.from_user.id, is_new_meal=is_new, meal_id=actual_meal_id, state=state)

async def unified_process_input(message: types.Message, text: str, user_id: int, is_new_meal: bool, meal_id: str = None, state: FSMContext = None):
    # 1. Parse
    parsed_items = await ai_service.parse_food_input(text)
    if not parsed_items:
        logging.error(f"Groq returned empty or failed for text: {text}")
        await message.answer("Извините, произошла ошибка при разборе текста (ИИ не смог распознать продукты). Попробуйте перефразировать.")
        return

    # 2. Group items by date/time (Meal grouping)
    meal_groups = {}
    now_full = datetime.now(USER_TZ)
    default_date = now_full.strftime("%Y-%m-%d")
    default_time = now_full.strftime("%H:%M")
    
    for name, weight, m_kcal, k_type, d, t in parsed_items:
        key_date = d if d else default_date
        key_time = t if t else default_time
        
        is_historical = (d is not None or t is not None)
        
        key = (key_date, key_time, is_historical)
        if key not in meal_groups:
            meal_groups[key] = []
        meal_groups[key].append((name, weight, m_kcal, k_type))

    # 3. Process each group
    pending_products = []
    processed_dates = set()
    
    for (d_val, t_val, is_hist), items in meal_groups.items():
        # Определяем timestamp
        try:
            timestamp_str = f"{d_val} {t_val}:00"
            dt_obj = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            dt_obj = dt_obj.replace(tzinfo=USER_TZ)
        except:
            dt_obj = now_full
        
        processed_dates.add(dt_obj.date())
        
        # ЛОГИКА ПЕРЕЗАПИСИ:
        # Если это исторический лог (указано время), мы сначала удаляем старые записи за эту секунду.
        # Это предотвращает дублирование при повторной отправке одного и того же лога.
        if is_hist:
            await repository.delete_meal_at_timestamp(user_id, dt_obj)
            curr_meal_id = str(uuid.uuid4())
            await repository.create_meal(curr_meal_id, user_id, timestamp=dt_obj)
        else:
            if is_new_meal:
                curr_meal_id = str(uuid.uuid4())
                await repository.create_meal(curr_meal_id, user_id, timestamp=dt_obj)
            else:
                curr_meal_id = meal_id if meal_id else str(uuid.uuid4())
                if not meal_id:
                    await repository.create_meal(curr_meal_id, user_id, timestamp=dt_obj)
                else:
                    await repository.update_meal_time(curr_meal_id)

        # Обработка продуктов
        for name, weight, m_kcal, k_type in items:
            final_total_kcal = 0
            kcal_per_100_for_db = None
            
            # НОВАЯ ЛОГИКА: Одно поле для ручного ввода
            if m_kcal is not None:
                if k_type == "total":
                    final_total_kcal = float(m_kcal)
                    kcal_per_100_for_db = (final_total_kcal / weight * 100) if weight > 0 else final_total_kcal
                else: # per_100
                    kcal_per_100_for_db = float(m_kcal)
                    final_total_kcal = (weight / 100) * kcal_per_100_for_db
                
                product = await repository.get_product(name)
                if not product:
                    pending_products.append({"name": name, "kcal": kcal_per_100_for_db})
            else:
                # Стандартный путь: База или ИИ
                product = await repository.get_product(name)
                if product:
                    kcal_per_100_for_db = product[2]
                else:
                    kcal_per_100_for_db = await ai_service.get_calories_info(name)
                    if kcal_per_100_for_db is None:
                        await state.update_data(polling_product={"name": name, "weight": weight, "meal_id": curr_meal_id, "text": text})
                        await state.set_state(FoodLogState.waiting_for_kcal)
                        await message.answer(f"Я не знаю калорийность '{name}'. Сколько в нем ккал на 100г?")
                        return 
                    pending_products.append({"name": name, "kcal": kcal_per_100_for_db})
                
                final_total_kcal = (weight / 100) * kcal_per_100_for_db
            
            await repository.add_log(user_id, curr_meal_id, name, weight, final_total_kcal, timestamp=dt_obj)

    # 4. Generate Reports
    try:
        for d_obj in sorted(processed_dates):
            logs = await repository.get_daily_logs(user_id, d_obj)
            report_text = await report.generate_day_report(logs)
            await message.answer(report_text)
    except Exception as e:
        logging.error(f"Error in report: {e}")

    # 5. Confirmation UI
    if pending_products:
        if state:
            await state.update_data(pending_add=pending_products)
        
        items_text = "\n".join([f"🔸 {p['name'].capitalize()}: {int(p['kcal'])} ккал" for p in pending_products])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Внести", callback_data="confirm_bulk_save")],
            [InlineKeyboardButton(text="❌ Не вносить", callback_data="cancel_action")]
        ])
        
        await message.answer(
            f"Внести новый / новые продукты в базу данных?\n\n{items_text}",
            reply_markup=kb
        )

# Регистрация коллбэков
@router.callback_query(F.data == "confirm_bulk_save")
async def handle_bulk_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pending = data.get('pending_add', [])
    if not pending:
        await callback.answer("Нет продуктов для сохранения.")
        return
    for p in pending:
        await repository.add_product(p['name'], p['kcal'], is_verified=True)
    await callback.message.edit_text(f"✅ Успешно добавлено продуктов: {len(pending)}")
    await state.update_data(pending_add=[])
    await callback.answer()

@router.message(FoodLogState.waiting_for_kcal)
async def handle_manual_kcal(message: types.Message, state: FSMContext):
    match = re.search(r"(\d+)", message.text)
    if not match:
        await message.answer("Пожалуйста, введите только число.")
        return
    
    kcal = float(match.group(1))
    data = await state.get_data()
    poll_data = data.get('polling_product')
    if not poll_data:
        await state.clear()
        return

    name, weight, meal_id = poll_data['name'], poll_data['weight'], poll_data['meal_id']
    await repository.add_log(message.from_user.id, meal_id, name, weight, (weight/100)*kcal)
    
    pending = data.get('pending_add', [])
    pending.append({"name": name, "kcal": kcal})
    await state.update_data(pending_add=pending)
    await state.set_state(None)
    
    # Репорт
    now = datetime.now(USER_TZ)
    logs = await repository.get_daily_logs(message.from_user.id, now.date())
    report_text = await report.generate_day_report(logs)
    await message.answer(report_text)
    
    # Подтверждение
    items_text = "\n".join([f"🔸 {p['name'].capitalize()}: {int(p['kcal'])} ккал" for p in pending])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Внести", callback_data="confirm_bulk_save")],
        [InlineKeyboardButton(text="❌ Не вносить", callback_data="cancel_action")]
    ])
    await message.answer(f"Внести новый / новые продукты в базу данных?\n\n{items_text}", reply_markup=kb)
@router.message(FoodLogState.waiting_for_date)
async def handle_custom_date(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    input_date = message.text.lower().strip()
    data = await state.get_data()
    food_text = data.get('text')
    
    target_date = None
    now = datetime.now(USER_TZ)
    
    # 1. Обработка относительных дат
    if "сегодня" in input_date:
        target_date = now
    elif "вчера" in input_date:
        from datetime import timedelta
        target_date = now - timedelta(days=1)
    elif "позавчера" in input_date:
        from datetime import timedelta
        target_date = now - timedelta(days=2)
    
    # 2. Обработка форматов дат (dd.mm.yy, dd.mm)
    if not target_date:
        # Паттерн: dd.mm.yyyy или dd.mm.yy или dd.mm
        match = re.search(r"(\d{1,2})[./](\d{1,2})([./](\d{2,4}))?", input_date)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = match.group(4)
            
            if year:
                year = int(year)
                if year < 100: year += 2000
            else:
                year = now.year
                
            try:
                target_date = datetime(year, month, day).replace(tzinfo=USER_TZ)
            except ValueError:
                await message.answer("❌ Некорректная дата. Попробуйте еще раз или напишите 'отмена'.")
                return

    if not target_date:
        if "отмена" in input_date:
            await state.clear()
            await message.answer("Действие отменено.")
            return
        await message.answer("🤷 Не смог распознать дату. Напишите, например, '21.01' или 'вчера'.")
        return

    # Формируем итоговый текст с датой для ИИ, чтобы он точно знал куда писать
    final_text = f"{target_date.strftime('%d/%m/%y')}\n{food_text}"
    
    await state.clear()
    await unified_process_input(message, final_text, user_id, is_new_meal=True, state=state)
