from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('Как пользоваться', callback_data='menu:help'),
                InlineKeyboardButton('Статистика', callback_data='menu:stats'),
            ],
            [
                InlineKeyboardButton('История', callback_data='history:1'),
                InlineKeyboardButton('Избранное', callback_data='favorites:1'),
            ],
            [
                InlineKeyboardButton('Поиск', callback_data='menu:search'),
                InlineKeyboardButton('Очередь', callback_data='menu:queue'),
            ],
            [
                InlineKeyboardButton('Очистить очередь', callback_data='menu:cancel'),
                InlineKeyboardButton('Состояние', callback_data='menu:status'),
            ],
        ]
    )


def result_actions(history_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('В избранное', callback_data=f'fav:{history_id}'),
                InlineKeyboardButton('Повторить', callback_data=f'repeat:{history_id}'),
            ],
            [InlineKeyboardButton('Главное меню', callback_data='menu:main')],
        ]
    )


def pager(kind: str, page: int, pages: int) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    if page > 1:
        row.append(InlineKeyboardButton('◀', callback_data=f'{kind}:{page - 1}'))
    row.append(InlineKeyboardButton(f'{page}/{pages}', callback_data='noop'))
    if page < pages:
        row.append(InlineKeyboardButton('▶', callback_data=f'{kind}:{page + 1}'))
    buttons.append(row)
    buttons.append([InlineKeyboardButton('Главное меню', callback_data='menu:main')])
    return InlineKeyboardMarkup(buttons)
