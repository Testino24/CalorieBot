from groq import Groq
import re
import json
from config import GROQ_API_KEY

# Инициализируем Groq клиент
client = Groq(api_key=GROQ_API_KEY)

# Выбор модели (быстрая и надежная)
MODEL_NAME = "llama-3.3-70b-versatile"  # Лучшая для парсинга текста

async def parse_food_input(text):
    """
    Разбирает текст с помощью Groq и возвращает список кортежей.
    """
    prompt = f"""Parse this food list into JSON. Return ONLY the JSON array, no explanations.

Input: {text}

Rules:
1. Extract food name in Russian (lowercase). Use singular form where possible.
2. IMPORTANT: Do NOT include weight or "kcal" in the "name" field.
3. IMPORTANT: Keep fat percentage in the name (e.g., 'творог 5%').
4. Extract weight in grams.
5. SPECIAL RULES for calories: 
   - Numbers in parentheses like "(X)" (e.g. "Product (150)") are ALWAYS `kcal_type`: "per_100".
   - If the input is "Product X ккал" OR "Product Yг - X ккал", set `manual_kcal` = X and `kcal_type`: "total".
   - If weight is not specified but there is "(X)", set weight=100.
6. TIME and DATE extraction:
   - Extract date in 'YYYY-MM-DD' format if mentioned (e.g. "1/22/26" or "23/01/26" -> "2026-01-23"). 
   - IMPORTANT: If a date appears, it applies to ALL following items until a new date is found.
   - Extract time in 'HH:MM' format if mentioned (e.g. "03:05").
   - Associate items with the most recent time/date mentioned above them. If none mentioned, use null.
7. Return ONLY this JSON format:
[{{"name": "str", "weight": number, "manual_kcal": number or null, "kcal_type": "per_100" | "total" | null, "date": "str or null", "time": "str or null"}}]

Example:
Input: "1/22/26\n03:05\nТворожная масса 200г - 304 ккал\n5:00\nКумыс 500г (100)"
Output: [
  {{"name": "творожная масса", "weight": 200, "manual_kcal": 304, "kcal_type": "total", "date": "2026-01-22", "time": "03:05"}},
  {{"name": "кумыс", "weight": 500, "manual_kcal": 100, "kcal_type": "per_100", "date": "2026-01-22", "time": "05:00"}}
]
"""
    
    try:
        # Используем Groq API (синхронный, оборачиваем в async)
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that parses food data into JSON. Return ONLY valid JSON array, no explanations."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=4000
        )
        
        # Получаем ответ
        text_response = response.choices[0].message.content
        
        # Очистка: ищем JSON массив в ответе
        cleaned_text = text_response.strip()
        
        # Убираем markdown
        cleaned_text = cleaned_text.replace("```json", "").replace("```", "").strip()
        
        # Ищем JSON массив (начинается с [ и заканчивается ])
        start_idx = cleaned_text.find('[')
        end_idx = cleaned_text.rfind(']')
        
        if start_idx != -1 and end_idx != -1:
            json_str = cleaned_text[start_idx:end_idx+1]
        else:
            json_str = cleaned_text
        
        # Парсим JSON
        data = json.loads(json_str)
        
        results = []
        for item in data:
            name = item.get('name')
            raw_weight = item.get('weight')
            weight = float(raw_weight) if raw_weight is not None else 0.0
            
            manual_kcal = item.get('manual_kcal')
            kcal_type = item.get('kcal_type')
            date = item.get('date')
            time = item.get('time')
            
            results.append((name, weight, manual_kcal, kcal_type, date, time))
            
        # Logging for debugging
        print(f"Groq parsed from '{text}':")
        for name, weight, m_kcal, k_type, d, t in results:
            print(f"  - {name}: {weight}g, manual: {m_kcal} ({k_type}), date: {d}, time: {t}")
            
        return results
        
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        print(f"Attempted to parse: {json_str if 'json_str' in locals() else cleaned_text}")
        return []
        
    except Exception as e:
        print(f"Groq parse error: {e}")
        return []

async def get_calories_info(product_name):
    """
    Ищет калорийность продукта через Groq.
    """
    prompt = f"""
    Сколько калорий в продукте '{product_name}' на 100 грамм?
    
    Важно:
    - ОБЯЗАТЕЛЬНО учитывай жирность/процент, если они указаны в названии (например, для 'творог 5%' и 'творог 9%' значения разные).
    - Если название неполное (например, "гречка"), предполагай самую распространённую приготовленную версию.
    - НИКОГДА не возвращай 0 для съедобных продуктов.
    - Если не уверен, предоставь среднюю оценку для этой категории еды.
    - Выведи только одно целое число.
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a nutrition expert. Answer with numbers only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=50
        )
        
        text = response.choices[0].message.content.strip()
        match = re.search(r'\d+', text)
        if match:
            kcal = int(match.group())
            print(f"Groq calories for '{product_name}': {kcal} kcал/100г")
            return kcal
        return None
        
    except Exception as e:
        print(f"Groq lookup error: {e}")
        return None
