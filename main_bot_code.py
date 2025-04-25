import os
import logging
import sqlite3
from datetime import datetime
from functools import wraps

from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.filters import Text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Bot token from environment variable
API_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
REQUIRED_CHANNEL_ID = os.getenv('REQUIRED_CHANNEL_ID')
REQUIRED_GROUP_ID = os.getenv('REQUIRED_GROUP_ID')
ADMIN_IDS = os.getenv('ADMIN_IDS', '').split(',')  # List of admin IDs

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# Configure Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# Initialize database
conn = sqlite3.connect('bot_database.db')
cursor = conn.cursor()

# Create users table
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    is_admin INTEGER DEFAULT 0,
    joined_date TEXT,
    last_active TEXT
)
''')

# Create conversation history table
cursor.execute('''
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    message TEXT,
    response TEXT,
    timestamp TEXT,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
)
''')

conn.commit()

# States for the conversation
class AdminStates(StatesGroup):
    waiting_for_admin_id = State()
    waiting_for_admin_action = State()
    waiting_for_message = State()


# Check if user is subscribed to channel and group
async def check_subscription(user_id):
    try:
        # Check channel subscription
        channel_member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL_ID, user_id=user_id)
        # Check group subscription
        group_member = await bot.get_chat_member(chat_id=REQUIRED_GROUP_ID, user_id=user_id)
        
        # If user is a member of both
        return (channel_member.status in ['member', 'administrator', 'creator'] and 
                group_member.status in ['member', 'administrator', 'creator'])
    except Exception as e:
        logging.error(f"Error checking subscription: {e}")
        return False


# Admin-only decorator
def admin_required(func):
    @wraps(func)
    async def wrapped(message, *args, **kwargs):
        user_id = str(message.from_user.id)
        
        # Check if user is in the admin list or database
        cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
        if user_id in ADMIN_IDS or (result and result[0] == 1):
            return await func(message, *args, **kwargs)
        else:
            await message.answer("Bu funksiya faqat adminlar uchun.")
            return
    return wrapped


# Helper to save user to database
def save_user(user):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
    INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, joined_date, last_active) 
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user.id, 
        user.username if user.username else '', 
        user.first_name if user.first_name else '', 
        user.last_name if user.last_name else '', 
        current_time, 
        current_time
    ))
    
    # Update last active if user already exists
    cursor.execute("""
    UPDATE users SET last_active = ? WHERE user_id = ?
    """, (current_time, user.id))
    
    conn.commit()


# Save conversation to database
def save_conversation(user_id, message, response):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
    INSERT INTO conversations (user_id, message, response, timestamp) 
    VALUES (?, ?, ?, ?)
    """, (user_id, message, response, timestamp))
    
    conn.commit()


# Create subscription keyboard
def get_subscription_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("Kanalga a'zo bo'lish", url=f"https://t.me/{REQUIRED_CHANNEL_ID.replace('@', '')}"),
        InlineKeyboardButton("Guruhga qo'shilish", url=f"https://t.me/{REQUIRED_GROUP_ID.replace('@', '')}"),
        InlineKeyboardButton("A'zolikni tekshirish", callback_data="check_subscription")
    )
    return keyboard


# Create admin keyboard
def get_admin_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("📊 Admin statistikasi"))
    keyboard.add(KeyboardButton("👤 Admin qo'shish"), KeyboardButton("🚫 Adminlikdan olish"))
    keyboard.add(KeyboardButton("📝 Barcha foydalanuvchilarga xabar"))
    keyboard.add(KeyboardButton("👥 Oddiy foydalanuvchi rejimi"))
    return keyboard


# Create main keyboard
def get_main_keyboard(user_id):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("🔗 Saytga o'tish"))
    
    # Check if user is admin to show admin panel button
    cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if str(user_id) in ADMIN_IDS or (result and result[0] == 1):
        keyboard.add(KeyboardButton("👑 Admin paneli"))
    
    return keyboard


@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    user = message.from_user
    save_user(user)
    
    # Check subscription
    if await check_subscription(user.id):
        await message.answer(
            f"Assalomu alaykum, {user.first_name}!\n"
            f"Botimizga xush kelibsiz. Menga savolingizni yuboring.",
            reply_markup=get_main_keyboard(user.id)
        )
    else:
        await message.answer(
            "Botdan foydalanish uchun quyidagi kanal va guruhga a'zo bo'ling:",
            reply_markup=get_subscription_keyboard()
        )


@dp.message_handler(commands=['stop'])
async def stop_command(message: types.Message):
    await message.answer(
        "Bot to'xtatildi. Qayta ishlash uchun /start buyrug'ini yuboring."
    )


@dp.message_handler(Text(equals="👑 Admin paneli"))
async def admin_panel(message: types.Message):
    user_id = message.from_user.id
    
    # Check if user is admin
    cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (str(user_id),))
    result = cursor.fetchone()
    
    if str(user_id) in ADMIN_IDS or (result and result[0] == 1):
        await message.answer("Admin paneliga xush kelibsiz!", reply_markup=get_admin_keyboard())
    else:
        await message.answer("Siz admin emassiz.")


@dp.message_handler(Text(equals="👥 Oddiy foydalanuvchi rejimi"))
async def user_mode(message: types.Message):
    await message.answer(
        "Siz oddiy foydalanuvchi rejimiga o'tdingiz.",
        reply_markup=get_main_keyboard(message.from_user.id)
    )


@dp.message_handler(Text(equals="📊 Admin statistikasi"))
@admin_required
async def admin_stats(message: types.Message):
    # Get total users count
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # Get active users in the last 24 hours
    cursor.execute("SELECT COUNT(*) FROM users WHERE last_active >= datetime('now', '-1 day')")
    active_users = cursor.fetchone()[0]
    
    # Get total conversations
    cursor.execute("SELECT COUNT(*) FROM conversations")
    total_conversations = cursor.fetchone()[0]
    
    await message.answer(
        f"📊 Bot statistikasi:\n\n"
        f"👥 Jami foydalanuvchilar: {total_users}\n"
        f"🔄 Faol foydalanuvchilar (24 soat): {active_users}\n"
        f"💬 Jami suhbatlar: {total_conversations}"
    )


@dp.message_handler(Text(equals="👤 Admin qo'shish"))
@admin_required
async def add_admin_start(message: types.Message):
    await AdminStates.waiting_for_admin_id.set()
    await message.answer("Yangi admin ID raqamini kiriting:")


@dp.message_handler(state=AdminStates.waiting_for_admin_id)
@admin_required
async def add_admin_process(message: types.Message, state: FSMContext):
    try:
        new_admin_id = message.text.strip()
        
        # Check if user exists
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (new_admin_id,))
        user = cursor.fetchone()
        
        if not user:
            await message.answer("Bu ID raqamli foydalanuvchi topilmadi. Foydalanuvchi avval botdan foydalangan bo'lishi kerak.")
            await state.finish()
            return
        
        # Update user as admin
        cursor.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (new_admin_id,))
        conn.commit()
        
        await message.answer(f"Foydalanuvchi (ID: {new_admin_id}) admin qilib tayinlandi.")
    except Exception as e:
        await message.answer(f"Xatolik yuz berdi: {str(e)}")
    
    await state.finish()


@dp.message_handler(Text(equals="🚫 Adminlikdan olish"))
@admin_required
async def remove_admin_start(message: types.Message):
    await AdminStates.waiting_for_admin_action.set()
    await message.answer("Adminlikdan olib tashlanadigan foydalanuvchi ID raqamini kiriting:")


@dp.message_handler(state=AdminStates.waiting_for_admin_action)
@admin_required
async def remove_admin_process(message: types.Message, state: FSMContext):
    try:
        admin_id = message.text.strip()
        
        # Admin cannot remove themselves or super admins from .env
        if str(message.from_user.id) == admin_id:
            await message.answer("Siz o'zingizni adminlikdan olib tashlay olmaysiz.")
            await state.finish()
            return
        
        if admin_id in ADMIN_IDS:
            await message.answer("Asosiy adminlarni olib tashlab bo'lmaydi.")
            await state.finish()
            return
        
        # Update user to remove admin status
        cursor.execute("UPDATE users SET is_admin = 0 WHERE user_id = ?", (admin_id,))
        conn.commit()
        
        await message.answer(f"Foydalanuvchi (ID: {admin_id}) adminlikdan olindi.")
    except Exception as e:
        await message.answer(f"Xatolik yuz berdi: {str(e)}")
    
    await state.finish()


@dp.message_handler(Text(equals="📝 Barcha foydalanuvchilarga xabar"))
@admin_required
async def broadcast_start(message: types.Message):
    await AdminStates.waiting_for_message.set()
    await message.answer("Barcha foydalanuvchilarga yuboriladigan xabarni kiriting:")


@dp.message_handler(state=AdminStates.waiting_for_message)
@admin_required
async def broadcast_message(message: types.Message, state: FSMContext):
    broadcast_text = message.text
    
    # Get all users
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    
    sent_count = 0
    error_count = 0
    
    await message.answer("Xabar yuborish boshlandi...")
    
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 ADMIN XABARI:\n\n{broadcast_text}")
            sent_count += 1
        except Exception as e:
            logging.error(f"Error sending message to {user[0]}: {e}")
            error_count += 1
    
    await message.answer(
        f"Xabar yuborish yakunlandi.\n"
        f"✅ Yuborildi: {sent_count}\n"
        f"❌ Xatolik: {error_count}"
    )
    await state.finish()


@dp.message_handler(Text(equals="🔗 Saytga o'tish"))
async def website_link(message: types.Message):
    # Check subscription before providing link
    if not await check_subscription(message.from_user.id):
        await message.answer(
            "Botdan foydalanish uchun quyidagi kanal va guruhga a'zo bo'ling:",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🌐 Saytga o'tish", url="https://example.com"))
    
    await message.answer("Saytimizga tashrif buyuring:", reply_markup=keyboard)


@dp.callback_query_handler(text="check_subscription")
async def check_subscription_callback(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    
    if await check_subscription(callback_query.from_user.id):
        await bot.send_message(
            callback_query.from_user.id,
            "✅ Siz kanalga va guruhga a'zo bo'lgansiz! Botdan foydalanishingiz mumkin.",
            reply_markup=get_main_keyboard(callback_query.from_user.id)
        )
    else:
        await bot.send_message(
            callback_query.from_user.id,
            "❌ Siz hali kerakli kanal va guruhga a'zo bo'lmagansiz.",
            reply_markup=get_subscription_keyboard()
        )


@dp.message_handler()
async def process_message(message: types.Message):
    user_id = message.from_user.id
    save_user(message.from_user)
    
    # Check subscription before processing message
    if not await check_subscription(user_id):
        await message.answer(
            "Botdan foydalanish uchun quyidagi kanal va guruhga a'zo bo'ling:",
            reply_markup=get_subscription_keyboard()
        )
        return
    
    # Process with Gemini AI
    try:
        user_message = message.text
        
        # Skip special commands for admin panel
        if user_message in ["👑 Admin paneli", "📊 Admin statistikasi", "👤 Admin qo'shish", 
                         "🚫 Adminlikdan olish", "📝 Barcha foydalanuvchilarga xabar", 
                         "👥 Oddiy foydalanuvchi rejimi", "🔗 Saytga o'tish"]:
            return
        
        # Send typing action
        await bot.send_chat_action(message.chat.id, "typing")
        
        # Get response from Gemini
        response = model.generate_content(user_message)
        response_text = response.text
        
        await message.answer(response_text)
        
        # Save conversation to database
        save_conversation(user_id, user_message, response_text)
        
    except Exception as e:
        logging.error(f"Error processing message: {e}")
        await message.answer("Xatolik yuz berdi. Iltimos, keyinroq qayta urinib ko'ring.")


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)