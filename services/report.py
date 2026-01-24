from datetime import datetime
import re

async def generate_day_report(daily_logs):
    """
    Generates a report string from daily logs rows.
    Rows: list of (meal_id, timestamp, product_name, weight_g, kcal_total)
    """
    if not daily_logs:
        return f"{datetime.now().strftime('%d/%m/%y')}\n\nНет данных."

    # Group by meal_id
    meals = {}
    order = []
    
    log_date_str = None
    
    for row in daily_logs:
        log_id, meal_id, timestamp_str, name, weight, kcal = row
        if isinstance(timestamp_str, str):
            # Самый надежный способ - вытащить цифры через regex
            # Ожидаем YYYY-MM-DD HH:MM:SS
            match = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", timestamp_str)
            if match:
                try:
                    dt = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M")
                except:
                    dt = datetime.now()
            else:
                dt = datetime.now()
        else:
            dt = timestamp_str

        if log_date_str is None:
            log_date_str = dt.strftime('%d/%m/%y')

        if meal_id not in meals:
            meals[meal_id] = {
                "time": dt,
                "items": [],
                "total": 0
            }
            order.append(meal_id)
        
        meals[meal_id]["items"].append((name, weight, kcal))
        meals[meal_id]["total"] += kcal

    # Build String
    header_date = log_date_str if log_date_str else datetime.now().strftime('%d/%m/%y')
    report = f"{header_date}\n\n"
    
    grand_total = 0
    order.sort(key=lambda mid: meals[mid]["time"])
    
    for mid in order:
        meal = meals[mid]
        time_str = meal["time"].strftime("%H:%M")
        report += f"{time_str}\n\n"
        
        for name, weight, kcal in meal["items"]:
            weight_str = f"{int(weight)}г " if weight > 0 else ""
            report += f"{name} {weight_str}- {int(kcal)} ккал\n"
            
        report += f"Итого {int(meal['total'])} ккал\n\n"
        grand_total += meal["total"]
        
    report += f"Всего {int(grand_total)} ккал"
    
    return report
