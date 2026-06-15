import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

logging.basicConfig(level=logging.INFO)

TOKEN = '8695787171:AAEBTLKPnWrT-8MF6G7d_HgBaOnAVbZsbgs'

def start(update: Update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text='Привет!')

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    start_handler = CommandHandler('start', start)
    app.add_handler(start_handler)

    app.run_polling()

if __name__ == '__main__':
    main()
