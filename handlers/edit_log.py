from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import repository
from services import report
from datetime import datetime
from config import USER_TZ
import re

router = Router()

class FoodEditState(StatesGroup):
    waiting_for_meal_selection = State()
    waiting_for_item_selection = State()
    waiting_for_action_selection = State()
    waiting_for_new_weight = State()
    waiting_for_new_kcal = State()

@router.message(Command("edit"))
async def cmd_edit(message: types.Message, state: FSMContext):
    """Показывает список приемов пищи за сегодня для редактирования."""
    await state.clear()
    user_id = message.from_user.id
    now = datetime.now(USER_TZ)
    logs = await repository.get_daily_logs(user_id, now.date())

    if not logs:
        await message.answer("Сегодня вы еще ничего не записывали.")
        return

    # Группируем по meal_id
    meals = {}
    for log_id, meal_id, ts, name, weight, kcal in logs:
        if isinstance(ts, str):
            # Парсим строку времени
            match = re.search(r"(\d{2}:\d{2})", ts)
            t_str = match.group(1) if match else "??:??"
        else:
            t_str = ts.strftime("%H:%M")
            
        if meal_id not in meals:
            meals[meal_id] = {"time": t_str, "count": 0}
        meals[meal_id]["count"] += 1

    keyboard = []
    # Сортируем по времени
    sorted_meals = sorted(meals.items(), key=lambda x: x[1]["time"])
    
    for meal_id, info in sorted_meals:
        keyboard.append([InlineKeyboardButton(
            text=f"🕒 {info['time']} ({info['count']} прод.)", 
            callback_data=f"edit_meal:{meal_id}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")])
    
    await message.answer(
        "Выберите прием пищи для редактирования:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@router.callback_query(F.data.startswith("edit_meal:"))
async def handle_meal_edit(callback: types.CallbackQuery, state: FSMContext):
    meal_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    now = datetime.now(USER_TZ)
    logs = await repository.get_daily_logs(user_id, now.date())
    
    # Фильтруем только нужный прием пищи
    items = [log for log in logs if log[1] == meal_id]
    
    if not items:
        await callback.answer("Прием пищи не найден.")
        return

    keyboard = []
    for log_id, m_id, ts, name, weight, kcal in items:
        w_text = f" ({int(weight)}г)" if weight > 0 else ""
        keyboard.append([InlineKeyboardButton(
            text=f"🍴 {name.capitalize()}{w_text} - {int(kcal)} ккал",
            callback_data=f"edit_item:{log_id}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="edit_back_to_meals")])
    
    await callback.message.edit_text(
        "Выберите продукт для изменения:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@router.callback_query(F.data == "edit_back_to_meals")
async def handle_back_to_meals(callback: types.CallbackQuery, state: FSMContext):
    await cmd_edit(callback.message, state) # reuse command logic
    await callback.answer()

@router.callback_query(F.data.startswith("edit_item:"))
async def handle_item_edit_menu(callback: types.CallbackQuery, state: FSMContext):
    log_id = int(callback.data.split(":")[1])
    item = await repository.get_log_entry(log_id)
    
    if not item:
        await callback.answer("Запись не найдена.")
        return
    
    _, name, weight, kcal, meal_id = item
    
    text = f"Редактирование: **{name}**\nТекущие данные: {int(weight)}г, {int(kcal)} ккал."
    
    keyboard = [
        [
            InlineKeyboardButton(text="⚖️ Вес", callback_data=f"action:weight:{log_id}"),
            InlineKeyboardButton(text="🔥 Калории", callback_data=f"action:kcal:{log_id}")
        ],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"action:delete:{log_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"edit_meal:{meal_id}")]
    ]
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("action:"))
async def handle_action(callback: types.CallbackQuery, state: FSMContext):
    _, action, log_id = callback.data.split(":")
    log_id = int(log_id)
    
    if action == "delete":
        await repository.delete_log_entry(log_id)
        await callback.answer("Запись удалена.")
        # Показываем обновленный отчет
        now = datetime.now(USER_TZ)
        logs = await repository.get_daily_logs(callback.from_user.id, now.date())
        report_text = await report.generate_day_report(logs)
        await callback.message.edit_text(f"✅ Удалено.\n\n{report_text}")
        
    elif action == "weight":
        await state.update_data(edit_log_id=log_id)
        await state.set_state(FoodEditState.waiting_for_new_weight)
        await callback.message.edit_text("Введите новый вес в граммах (только число):")
        await callback.answer()
        
    elif action == "kcal":
        await state.update_data(edit_log_id=log_id)
        await state.set_state(FoodEditState.waiting_for_new_kcal)
        await callback.message.edit_text("Введите новое общее количество калорий:")
        await callback.answer()

@router.message(FoodEditState.waiting_for_new_weight)
async def process_new_weight(message: types.Message, state: FSMContext):
    match = re.search(r"(\d+)", message.text)
    if not match:
        await message.answer("Пожалуйста, введите число.")
        return
    
    new_weight = float(match.group(1))
    data = await state.get_data()
    log_id = data.get('edit_log_id')
    
    item = await repository.get_log_entry(log_id)
    if item:
        _, name, old_weight, old_total_kcal, meal_id = item
        # Пропорционально пересчитываем калории
        if old_weight > 0:
            kcal_per_1g = old_total_kcal / old_weight
            new_kcal = kcal_per_1g * new_weight
        else:
            # Если раньше был 0, берем из базы или ставим 0
            product = await repository.get_product(name)
            kcal_per_100 = product[2] if product else 0
            new_kcal = (new_weight / 100) * kcal_per_100
            
        await repository.update_log_entry(log_id, weight=new_weight, kcal=new_kcal)
        await message.answer(f"✅ Вес изменен на {int(new_weight)}г. Калории пересчитаны.")
        
        # Показываем отчет
        now = datetime.now(USER_TZ)
        logs = await repository.get_daily_logs(message.from_user.id, now.date())
        report_text = await report.generate_day_report(logs)
        await message.answer(report_text)
    
    await state.clear()

@router.message(FoodEditState.waiting_for_new_kcal)
async def process_new_kcal(message: types.Message, state: FSMContext):
    match = re.search(r"(\d+)", message.text)
    if not match:
        await message.answer("Пожалуйста, введите число.")
        return
    
    new_kcal = float(match.group(1))
    data = await state.get_data()
    log_id = data.get('edit_log_id')
    
    await repository.update_log_entry(log_id, kcal=new_kcal)
    await message.answer(f"✅ Калории изменены на {int(new_kcal)} ккал.")
    
    # Показываем отчет
    now = datetime.now(USER_TZ)
    logs = await repository.get_daily_logs(message.from_user.id, now.date())
    report_text = await report.generate_day_report(logs)
    await message.answer(report_text)
    
    await state.clear()
