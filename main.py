import os
import sqlite3
import random
import schedule
import time
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # e.g., "@YourChannel"
GROUP_ID = os.getenv("GROUP_ID")  # e.g., "@YourGroup"
WEBSITE_URL = os.getenv("WEBSITE_URL")  # e.g., "https://yourwebsite.com"
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS").split(",")]  # Comma-separated admin IDs
MOTIVATION_GROUP_ID = os.getenv("MOTIVATION_GROUP_ID")  # Group for motivation submissions

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# Database setup
def init_db():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, is_active INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS motivations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        text TEXT, 
        submitted_by INTEGER, 
        status TEXT, 
        schedule_date TEXT,
        message_id INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS broadcasts (id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT, media TEXT)''')
    conn.commit()
    conn.close()

# Check membership
async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        channel_status = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        group_status = await context.bot.get_chat_member(GROUP_ID, user_id)
        return channel_status.status in ['member', 'administrator', 'creator'] and \
               group_status.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

# Main keyboard
def get_main_keyboard():
    keyboard = [
        ["Yordam", "Biz haqimizda"],
        ["Kanal", "Guruh", "Veb sayt"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Inline keyboard for membership
def get_membership_keyboard():
    keyboard = [
        [InlineKeyboardButton("Kanalga a'zo bo'lish", url=f"https://t.me/{CHANNEL_ID[1:]}")],
        [InlineKeyboardButton("Guruhga a'zo bo'lish", url=f"https://t.me/{GROUP_ID[1:]}")],
        [InlineKeyboardButton("Tekshirish", callback_data="check_membership")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, username, is_active) VALUES (?, ?, ?)", 
              (user_id, update.effective_user.username, 1))
    conn.commit()
    conn.close()

    if await check_membership(user_id, context):
        await update.message.reply_text(
            "Botga xush kelibsiz! Quyidagi tugmalardan foydalaning:", 
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            "Botdan foydalanish uchun kanal va guruhga a'zo bo'ling:", 
            reply_markup=get_membership_keyboard()
        )

# Stop command
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("Bot to'xtatildi. Qayta boshlash uchun /start buyrug'ini yuboring.")

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    Bot buyruqlari:
    /start - Botni boshlash
    /stop - Botni to'xtatish
    /help - Yordam
    /ai - Sun'iy intellekt bilan suhbat
    /about - Biz haqimizda
    Motivatsiya yuborish uchun oddiy xabar sifatida yozing.
    """
    await update.message.reply_text(help_text, reply_markup=get_main_keyboard())

# About command
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = "Bizning loyiha haqida: Bu Telegram bot foydalanuvchilarga motivatsiya, yangiliklar va AI bilan suhbat imkonini beradi."
    await update.message.reply_text(about_text, reply_markup=get_main_keyboard())

# AI conversation
async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_membership(update.effective_user.id, context):
        await update.message.reply_text(
            "AI bilan suhbatlashish uchun kanal va guruhga a'zo bo'ling:", 
            reply_markup=get_membership_keyboard()
        )
        return
    await update.message.reply_text("Gemini AI bilan suhbat boshlandi. Savolingizni yozing:")
    context.user_data['ai_mode'] = True

# Handle text messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if text in ["Yordam"]:
        await help_command(update, context)
        return
    elif text in ["Biz haqimizda"]:
        await about(update, context)
        return
    elif text == "Kanal":
        await update.message.reply_text(f"Kanal: https://t.me/{CHANNEL_ID[1:]}")
        return
    elif text == "Guruh":
        await update.message.reply_text(f"Guruh: https://t.me/{GROUP_ID[1:]}")
        return
    elif text == "Veb sayt":
        await update.message.reply_text(f"Veb sayt: {WEBSITE_URL}")
        return

    if context.user_data.get('ai_mode', False):
        try:
            response = model.generate_content(text)
            await update.message.reply_text(response.text)
        except Exception as e:
            await update.message.reply_text(f"Xato yuz berdi: {str(e)}")
        return

    # Handle motivation submission
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO motivations (text, submitted_by, status) VALUES (?, ?, ?)", 
              (text, user_id, 'pending'))
    motivation_id = c.lastrowid
    conn.commit()
    conn.close()

    # Notify admins in motivation group
    keyboard = [
        [InlineKeyboardButton("Qabul qilish", callback_data=f"approve_{motivation_id}"),
         InlineKeyboardButton("Bekor qilish", callback_data=f"reject_{motivation_id}")],
        [InlineKeyboardButton("1 kun", callback_data=f"schedule_{motivation_id}_1"),
         InlineKeyboardButton("2 kun", callback_data=f"schedule_{motivation_id}_2"),
         InlineKeyboardButton("3 kun", callback_data=f"schedule_{motivation_id}_3")]
    ]
    await context.bot.send_message(
        MOTIVATION_GROUP_ID, 
        f"Yangi motivatsiya:\n{text}\nYuboruvchi: @{update.effective_user.username}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("Motivatsiyangiz adminga yuborildi. Tasdiqlanishini kuting.")

# Admin broadcast
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
        return
    if not context.args:
        await update.message.reply_text("Xabar yuborish uchun matn kiriting: /broadcast Xabar matni")
        return
    message = " ".join(context.args)
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_active = 1")
    users = c.fetchall()
    for user in users:
        try:
            await context.bot.send_message(user[0], message)
        except Exception as e:
            logger.error(f"Error sending broadcast to {user[0]}: {e}")
    conn.close()
    await update.message.reply_text("Xabar barcha foydalanuvchilarga yuborildi.")

# Callback queries
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "check_membership":
        if await check_membership(query.from_user.id, context):
            await query.message.edit_text("Tabriklaymiz! Endi botdan foydalanishingiz mumkin.", 
                                         reply_markup=None)
            await context.bot.send_message(query.from_user.id, 
                                          "Botga xush kelibsiz!", 
                                          reply_markup=get_main_keyboard())
        else:
            await query.message.edit_text("Iltimos, kanal va guruhga a'zo bo'ling:", 
                                         reply_markup=get_membership_keyboard())
        return

    if data.startswith("approve_"):
        motivation_id = int(data.split("_")[1])
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute("UPDATE motivations SET status = 'approved' WHERE id = ?", (motivation_id,))
        c.execute("SELECT text FROM motivations WHERE id = ?", (motivation_id,))
        text = c.fetchone()[0]
        conn.commit()
        conn.close()

        # Send to all users with like/share buttons
        keyboard = [
            [InlineKeyboardButton("👍 Like", callback_data=f"like_{motivation_id}"),
             InlineKeyboardButton("📤 Ulashish", switch_inline_query=text)]
        ]
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE is_active = 1")
        users = c.fetchall()
        for user in users:
            try:
                await context.bot.send_message(user[0], text, reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as e:
                logger.error(f"Error sending motivation to {user[0]}: {e}")
        conn.close()
        await query.message.edit_text(f"Motivatsiya tasdiqlandi va yuborildi:\n{text}")

    elif data.startswith("reject_"):
        motivation_id = int(data.split("_")[1])
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute("UPDATE motivations SET status = 'rejected' WHERE id = ?", (motivation_id,))
        conn.commit()
        conn.close()
        await query.message.edit_text("Motivatsiya bekor qilindi.")

    elif data.startswith("schedule_"):
        motivation_id, days = data.split("_")[1], data.split("_")[2]
        schedule_date = (datetime.now() + timedelta(days=int(days))).strftime('%Y-%m-%d')
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute("UPDATE motivations SET status = 'approved', schedule_date = ? WHERE id = ?", 
                  (schedule_date, motivation_id))
        conn.commit()
        conn.close()
        await query.message.edit_text(f"Motivatsiya {days} kundan keyin yuboriladi.")

    elif data.startswith("like_"):
        await query.message.edit_text(f"{query.message.text}\n👍 Sizga yoqdi!")

# Daily motivation
def send_daily_motivation(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT text FROM motivations WHERE status = 'approved' AND (schedule_date IS NULL OR schedule_date = ?)", 
              (datetime.now().strftime('%Y-%m-%d'),))
    motivations = c.fetchall()
    if motivations:
        motivation = random.choice(motivations)[0]
        c.execute("SELECT user_id FROM users WHERE is_active = 1")
        users = c.fetchall()
        for user in users:
            try:
                context.job_queue.run_once(
                    lambda ctx: ctx.bot.send_message(user[0], motivation, 
                                                   reply_markup=InlineKeyboardMarkup([
                                                       [InlineKeyboardButton("👍 Like", callback_data="like_daily"),
                                                        InlineKeyboardButton("📤 Ulashish", switch_inline_query=motivation)]
                                                   ])),
                    0
                )
            except Exception as e:
                logger.error(f"Error sending daily motivation to {user[0]}: {e}")
    conn.close()

# Schedule daily motivation at 8:00 AM
schedule.every().day.at("08:00").do(lambda: send_daily_motivation)

async def run_scheduler():
    while True:
        schedule.run_pending()
        await asyncio.sleep(60)

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ai", ai_command))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run scheduler in background
    asyncio.get_event_loop().create_task(run_scheduler())
    app.run_polling()

if __name__ == "__main__":
    main()
