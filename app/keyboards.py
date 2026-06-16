from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    """Главное меню"""
    keyboard = [
        [
            InlineKeyboardButton("📖 Помощь", callback_data="menu:help"),
            InlineKeyboardButton("📊 Статистика", callback_data="menu:stats"),
        ],
        [
            InlineKeyboardButton("📜 История", callback_data="menu:history"),
            InlineKeyboardButton("⭐ Избр��нное", callback_data="menu:favorites"),
        ],
        [
            InlineKeyboardButton("⚙️ Статус", callback_data="menu:status"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def result_actions(history_id: int) -> InlineKeyboardMarkup:
    """Меню действий с результатом"""
    keyboard = [
        [
            InlineKeyboardButton("⭐ В избранное", callback_data=f"fav:{history_id}"),
            InlineKeyboardButton("🔁 Повторить", callback_data=f"repeat:{history_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
