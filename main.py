import os
import sys
import logging
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ElevenLabsBotMain")

# Import project modules
import database as db
from handlers import router
from web_server import create_web_app

async def main():
    logger.info("Initializing Database...")
    db.init_db()
    
    bot_token = os.environ.get("ELEVENLABS_BOT_TOKEN")
    if not bot_token:
        logger.error("CRITICAL: ELEVENLABS_BOT_TOKEN environment variable is not set!")
        sys.exit(1)
        
    logger.info("Starting ElevenLabs Voice Bot...")
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    dp = Dispatcher()
    dp.include_router(router)
    
    # Configure the bot command list
    try:
        from aiogram.types import BotCommand
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="profile", description="Профиль и лимиты"),
            BotCommand(command="help", description="Инструкция по озвучке")
        ])
        logger.info("Voice bot commands set successfully.")
    except Exception as e:
        logger.warning(f"Could not set voice bot commands: {e}")
        
    port = int(os.environ.get("PORT_VOICE", "8081"))
    host = os.environ.get("HOST_VOICE", "0.0.0.0")
    
    web_app = create_web_app(bot)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    
    logger.info(f"Starting Voice Web Server on port {port}...")
    await site.start()
    
    logger.info("Starting Voice Telegram Bot polling...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Voice Bot execution error: {e}")
        logger.info("Keeping Web App Server alive on port 8081...")
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Voice Bot stopped.")
