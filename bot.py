
import telebot
import schedule
import time
from threading import Thread
from database import Database
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from telebot import types

TOKEN = 'ТУТ ТОКЕН'

bot = telebot.TeleBot(TOKEN)
db = Database()

# Настройка логирования
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("bot.log"),
                        logging.StreamHandler()
                    ])


# Define the menu keyboard
def get_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    start_button = types.KeyboardButton("🎊Старт🎊")
    show_button = types.KeyboardButton("Показать🔎")
    nc_button = types.KeyboardButton("Ты...❤️")
    menu_button = types.KeyboardButton("Помощь🆘")
    time_button = types.KeyboardButton("Время⏳")
    keyboard.add(start_button, show_button, nc_button, time_button, menu_button)
    return keyboard




# COMMAND
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id

    if user_id in [1026824739, 7258801885, 969625434]:
        if not db.user_exists(user_id):
            lines = [
                "Строка 1", "Строка 2", "Строка 3", "Строка 4", "Строка 5",
                "Строка 6"
                # "Строка 7", "Строка 8", "Строка 9", "Строка 10",
                # "Строка 11", "Строка 12", "Строка 13", "Строка 14", "Строка 15",
                # "Строка 16", "Строка 17", "Строка 18", "Строка 19", "Строка 20",
                # "Строка 21", "Строка 22", "Строка 23", "Строка 24", "Строка 25",
                # "Строка 26", "Строка 27", "Строка 28", "Строка 29", "Строка 30",
                # "Строка 31", "Строка 32"
            ]
            photo_paths = [
                "/home/sevase/TgBot/res/Images/img1.png", "/home/sevase/TgBot/res/Images/img2.png", "/home/sevase/TgBot/res/Images/img3.png", "/home/sevase/TgBot/res/Images/img4.png",
                "/home/sevase/TgBot/res/Images/img5.png", "/home/sevase/TgBot/res/Images/img6.png"
                # "res/Images/img7.png", "res/Images/img8.png",
                # "res/Images/img9.png", "res/Images/img10.png", "res/Images/img11.png", "res/Images/img12.png",
                # "res/Images/img13.png", "res/Images/img14.png", "res/Images/img15.png", "res/Images/img16.png",
                # "res/Images/img17.png", "res/Images/img18.png", "res/Images/img19.png", "res/Images/img20.png",
                # "res/Images/img21.png", "res/Images/img22.png", "res/Images/img23.png", "res/Images/img24.png",
                # "res/Images/img25.png", "res/Images/img26.png", "res/Images/img27.png", "res/Images/img28.png",
                # "res/Images/img29.png", "res/Images/img30.png", "res/Images/img31.png", "res/Images/img32.png"
            ]

            db.fill_database_for_user(user_id, lines, photo_paths)
            bot.send_message(user_id,
                             "Игорь ТЕСТЬ НАХООООООООООООООЙ",
                             reply_markup=get_menu_keyboard())
            logging.info(f"New user {user_id} registered and database filled.")
        else:
            bot.send_message(user_id, "Ты уже зареган!", reply_markup=get_menu_keyboard())
            logging.info(f"User {user_id} attempted to register again.")
    else:
        bot.send_message(user_id, "Пишов нахой!")
        logging.warning(f"Unauthorized user {user_id} attempted to use the bot.")


@bot.message_handler(commands=['show'])
def show_poem(message):
    user_id = message.chat.id

    try:
        full = db.get_full_poem(user_id)
        bot.send_message(user_id, full, reply_markup=get_menu_keyboard())
        logging.info(f"User {user_id} requested full poem.")
    except:
        bot.send_message(user_id, "Строк стихотворения у тебя еще нету...😕", reply_markup=get_menu_keyboard())
        logging.info(f"User {user_id} error full poem.")


@bot.message_handler(commands=['ncfeel'])
def show_nc(message):
    import json
    import random
    user_id = message.chat.id

    with open('/home/sevase/TgBot/res/StructFile/phrs.json', 'r', encoding='utf-8') as file:
        data = json.load(file)

    phrases = data['phrases']
    rnd = random.choice(phrases)
    bot.send_message(user_id, rnd, reply_markup=get_menu_keyboard())


@bot.message_handler(commands=['time'])
def show_time(message):
    from datetime import datetime, timedelta
    user_id = message.chat.id

    try:
        now = datetime.now()
        row_time = now.replace(hour=12, minute=0, second=0, microsecond=0)

        if now > row_time:
            row_time += timedelta(days=1)
        answ_time = row_time - now

        # Извлекаем количество часов, минут и секунд
        hour = answ_time.seconds // 3600
        min = (answ_time.seconds % 3600) // 60
        sec = answ_time.seconds % 60

        bot.send_message(user_id, f"До отправки следующей строки стихотворения осталось: \n{hour} часов⏳ \n{min} минут⏳ \n{sec} секунд⏳", reply_markup=get_menu_keyboard())
        logging.info(f"User {user_id} requested time.")
    except:
        bot.send_message(user_id, "Со временем ошибка какая то...😕", reply_markup=get_menu_keyboard())
        logging.info(f"User {user_id} error time.")


# WORK FUNC
def send_daily_line():
    logging.info("send_daily_line started")
    user_ids = get_all_users()
    logging.info(f"Users to send: {user_ids}")

    for user_id in user_ids:
        res = db.get_next_line(user_id)
        if res:
            line_id, line, photo = res
            photo_path = f'temp_photo_{user_id}.jpg'
            with open(photo_path, 'wb') as f:
                f.write(photo)
            with open(photo_path, 'rb') as photo_file:
                bot.send_photo(user_id, photo=photo_file, caption=line)
            db.save_sent_line(user_id, line)
            logging.info(f"Sent line to user {user_id}: {line}")
        else:
            bot.send_message(user_id, "Все строки и фотографии уже отправлены. ❤️С днём рождения!!!❤️")
            logging.info(f"User {user_id} has received all lines and photos.")

    logging.info("send_daily_line finished")

def get_all_users():
    db.cursor.execute('SELECT DISTINCT user_id FROM poem')
    users = [row[0] for row in db.cursor.fetchall()]
    logging.info(f"Пользователи из базы данных: {users}")
    return users

def schedule_daily_task():
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_daily_line, 'cron', hour=12, minute=0)
    scheduler.start()
    logging.info("Scheduler started")

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logging.info("Scheduler stopped")




#HANDLERS
@bot.message_handler(func=lambda message: message.text == "Помощь🆘")
def show_menu(message):
    menu_text = ("Доступные команды:\n"
                 "✨ /start - Зарегистрируйся и получай ежедневные строчки стиха\n"
                 "✨ /show - Покажет все собраные строки стиха\n"
                 "✨ /nсfeel - Пришлет любую приятную фразу тебе\n"
                 "✨ /time - Пришлет тебе остаток времени, до следующей строки\n")

    bot.send_message(message.chat.id, menu_text, reply_markup=get_menu_keyboard())
    logging.info(f"User {message.chat.id} requested the help.")

@bot.message_handler(func=lambda message: message.text == "🎊Старт🎊")
def show_start(message):
    start(message)
    logging.info(f"User {message.chat.id} requested the start.")

@bot.message_handler(func=lambda message: message.text == "Показать🔎")
def show_sh_poem(message):
    show_poem(message)
    logging.info(f"User {message.chat.id} requested the show.")

@bot.message_handler(func=lambda message: message.text == "Ты...❤️")
def show_ncfeel(message):
    show_nc(message)
    logging.info(f"User {message.chat.id} requested the ncfeel.")

@bot.message_handler(func=lambda message: message.text == "Время⏳")
def show_ncfeel(message):
    show_time(message)
    logging.info(f"User {message.chat.id} requested time.")


if __name__ == '__main__':
    thread = Thread(target=schedule_daily_task)
    thread.start()
    logging.info("Starting bot polling.")
    bot.polling(non_stop=True, long_polling_timeout=30)
    logging.info("Bot polling started.")













