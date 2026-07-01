import os
import logging
import urllib.parse
from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import database as db

logger = logging.getLogger("ElevenLabsBotHandlers")
router = Router()

def get_webapp_url_for_user(user_id: int, username: str = ""):
    base_url = os.environ.get("WEBAPP_URL_VOICE", "http://localhost:8081").rstrip("/")
    separator = "&" if "?" in base_url else "?"
    username_encoded = urllib.parse.quote(username or "")
    return f"{base_url}{separator}user_id={user_id}&username={username_encoded}&v=1"

@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # Ensure user exists in database
    db.create_user(user_id, username)
    
    url = get_webapp_url_for_user(user_id, username)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎙️ Открыть Web-Синтезатор", url=url)]
    ])
    
    welcome_text = (
        f"👋 **Приветствуем вас в ElevenLabs AI Voice!**\n\n"
        f"🤖 Это передовой сервис озвучки и клонирования голосов в Telegram!\n\n"
        f"✨ **Что вы можете делать здесь:**\n"
        f"• Озвучивать текст реалистичными голосами от ElevenLabs.\n"
        f"• Клонировать собственные голоса за 1 минуту (доступно на Pro).\n"
        f"• Сохранять историю генераций и делиться аудио.\n\n"
        f"👇 Нажмите на кнопку ниже, чтобы открыть веб-интерфейс в браузере и начать работу:"
    )
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        db.create_user(user_id, message.from_user.username or message.from_user.first_name)
        user = db.get_user(user_id)
        
    sub_name = "Бесплатный"
    if user["sub_type"] == "starter":
        sub_name = "Starter 30k"
    elif user["sub_type"] == "pro":
        sub_name = "Pro 100k + Клонирование"
        
    url = get_webapp_url_for_user(user_id, user["username"])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Продлить / Купить подписку", url=url)]
    ])
    
    profile_text = (
        f"👑 **Личный кабинет ElevenLabs Voice**\n\n"
        f"👤 **Telegram ID:** `{user['telegram_id']}`\n"
        f"📊 **Тарифный план:** `{sub_name}`\n"
        f"⏳ **Действует до:** `{user['sub_until'] or 'Бессрочно'}`\n"
        f"✍️ **Осталось символов:** ` {user['char_limit']} / 30 000`\n"
    )
    await message.answer(profile_text, reply_markup=keyboard, parse_mode="Markdown")

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        f"💡 **Справка по использованию бота:**\n\n"
        f"1️⃣ Нажмите кнопку **🎙️ Открыть Web-Синтезатор** (или напишите /start).\n"
        f"2️⃣ Вставьте текст, выберите подходящий голос (вы можете прослушать его перед этим).\n"
        f"3️⃣ Нажмите кнопку **Сгенерировать озвучку**.\n"
        f"4️⃣ Аудиозапись будет доступна для прослушивания и скачивания в вашем плеере прямо на веб-странице!\n\n"
        f"👑 **Тарифные планы:**\n"
        f"• **Starter:** 350₽ / мес — 30 000 символов, стандартный набор голосов.\n"
        f"• **Pro:** 850₽ / мес — 100 000 символов, клонирование голоса, приоритетная генерация."
    )
    await message.answer(help_text, parse_mode="Markdown")
