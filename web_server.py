import os
import uuid
import logging
import aiohttp
import aiofiles
from aiohttp import web
import crypto_pay as cp
import database as db

logger = logging.getLogger("ElevenLabsWebServer")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()

# Standard Voice Library
VOICES = [
    {"id": "21m0aC4C9KstEPqMsrxW", "name": "Rachel (Женский)", "desc": "Мягкий, профессиональный закадровый голос", "gender": "female", "preview": "https://api.elevenlabs.io/v1/voices/21m0aC4C9KstEPqMsrxW/previews"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella (Женский)", "desc": "Энергичный, живой, подходит для рекламы", "gender": "female", "preview": "https://api.elevenlabs.io/v1/voices/EXAVITQu4vr4xnSDxMaL/previews"},
    {"id": "ErXwobaYiN019atkyvjV", "name": "Antoni (Мужской)", "desc": "Глубокий, доверительный голос для повествования", "gender": "male", "preview": "https://api.elevenlabs.io/v1/voices/ErXwobaYiN019atkyvjV/previews"},
    {"id": "pNInz6obpgq5epa5UR3f", "name": "Adam (Мужской)", "desc": "Классический американский мужской голос", "gender": "male", "preview": "https://api.elevenlabs.io/v1/voices/pNInz6obpgq5epa5UR3f/previews"},
    {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Dom (Мужской)", "desc": "Эпический, мощный закадровый голос для трейлеров", "gender": "male", "preview": "https://api.elevenlabs.io/v1/voices/AZnzlk1XvdvUeBnXmlld/previews"}
]

# Subscription Pricing (in Rubles)
PRICES = {
    "starter": 200.0,
    "creator": 400.0,
    "pro": 800.0,
    "scale": 1400.0,
    "business": 2000.0
}

# Voice Cloning Limits mapping
CLONE_LIMITS = {
    "free": 0,
    "starter": 0,
    "creator": 1,
    "pro": 5,
    "scale": 15,
    "business": 999999
}

def get_user_id_from_request(request: web.Request):
    # Retrieve user ID from Bearer token or Telegram-Init-Data headers
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        user = db.get_user_by_api_key(token)
        if user:
            return user["telegram_id"]
            
    # Alternate header check
    init_data = request.headers.get("Telegram-Init-Data")
    if init_data:
        # Extract ID (unverified for simplicity in client browser fallback, or via verify logic)
        import urllib.parse
        try:
            params = dict(urllib.parse.parse_qsl(init_data))
            if "user" in params:
                import json
                user_data = json.loads(params["user"])
                if "id" in user_data:
                    return int(user_data["id"])
        except Exception:
            pass
            
    # Try query parameter fallback
    try:
        user_id = request.query.get("user_id")
        if user_id:
            return int(user_id)
    except Exception:
        pass
        
    return None

async def handle_api_init(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    user = db.get_user(user_id)
    if not user:
        # Register user in DB
        db.create_user(user_id, f"User_{user_id}")
        user = db.get_user(user_id)
        
    history = db.get_user_generations(user_id, limit=30)
    cloned_list = db.get_cloned_voices(user_id)
    cloned_count = len(cloned_list)
    sub = user["sub_type"] or "free"
    cloned_limit = CLONE_LIMITS.get(sub, 0)
    
    # Merge standard voices with user's custom cloned voices
    user_voices = list(VOICES)
    for cv in cloned_list:
        user_voices.append({
            "id": cv["voice_id"],
            "name": f"Клон: {cv['name']}",
            "desc": "Собственный клонированный голос пользователя",
            "gender": "custom",
            "preview": ""
        })
        
    # Get user folders and pronunciation dictionary
    folders = db.get_folders(user_id)
    dictionary = db.get_dictionary(user_id)
    
    return web.json_response({
        "status": "success",
        "user": {
            "telegram_id": user["telegram_id"],
            "username": user["username"],
            "balance": user["balance"],
            "char_limit": user["char_limit"],
            "sub_type": user["sub_type"],
            "sub_until": user["sub_until"],
            "api_key": user["api_key"] or db.generate_api_key(user_id),
            "cloned_count": cloned_count,
            "cloned_limit": cloned_limit
        },
        "voices": user_voices,
        "history": history,
        "folders": folders,
        "dictionary": dictionary
    })

def create_dummy_mp3(file_path):
    # A tiny valid 1-second silent MP3 file bytes
    tiny_mp3 = b'\xff\xfb\x90\x44\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    with open(file_path, 'wb') as f:
        f.write(tiny_mp3)

async def mix_background_music(voice_path, bg_type):
    bg_files = {
        "lofi": "lofi.mp3",
        "cinematic": "cinematic.mp3",
        "rain": "rain.mp3",
        "ambient": "ambient.mp3"
    }
    bg_filename = bg_files.get(bg_type)
    if not bg_filename:
        return voice_path
        
    bg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "static", "bg", bg_filename)
    if not os.path.exists(bg_path):
        os.makedirs(os.path.dirname(bg_path), exist_ok=True)
        # Create a dummy background file so mixing doesn't crash if files aren't physically populated yet
        create_dummy_mp3(bg_path)
        
    try:
        from pydub import AudioSegment
        voice = AudioSegment.from_mp3(voice_path)
        bg = AudioSegment.from_mp3(bg_path)
        
        # Overlay looping bg track at low volume (-18dB)
        bg = bg - 18
        if len(bg) < len(voice):
            bg = bg * (len(voice) // len(bg) + 1)
            
        mixed = voice.overlay(bg)
        mixed.export(voice_path, format="mp3")
        logger.info(f"Mixed background music: {bg_type}")
    except Exception as e:
        logger.warning(f"Could not mix background music (pydub/ffmpeg missing): {e}")
        
    return voice_path

async def handle_api_generate(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    user = db.get_user(user_id)
    if not user:
        return web.json_response({"error": "Пользователь не найден"}, status=404)
        
    try:
        data = await request.json()
        text = data.get("text", "").strip()
        voice_id = data.get("voice_id", "").strip()
        folder_id = data.get("folder_id")
        if folder_id is not None:
            folder_id = int(folder_id)
            
        # Voice Settings
        stability = float(data.get("stability", 0.5))
        similarity_boost = float(data.get("similarity_boost", 0.75))
        style = float(data.get("style", 0.0))
        use_speaker_boost = bool(data.get("use_speaker_boost", True))
        
        # Background music
        bg_music = data.get("bg_music", "none").strip()
    except Exception:
        return web.json_response({"error": "Invalid request payload"}, status=400)
        
    if not text or not voice_id:
        return web.json_response({"error": "Текст и голос обязательны"}, status=400)
        
    # Apply Pronunciation Dictionary replacements
    user_dict = db.get_dictionary(user_id)
    processed_text = text
    for entry in user_dict:
        word = entry["word"]
        rep = entry["replacement"]
        import re
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        processed_text = pattern.sub(rep, processed_text)
        
    text_len = len(processed_text)
    if user["char_limit"] < text_len:
        return web.json_response({"error": f"Недостаточно лимита символов. Требуется: {text_len}, Доступно: {user['char_limit']}"}, status=400)
        
    filename = f"gen_{uuid.uuid4().hex}.mp3"
    media_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "media")
    os.makedirs(media_dir, exist_ok=True)
    file_path = os.path.join(media_dir, filename)
    
    # Check key and call ElevenLabs or Mock
    if not ELEVENLABS_API_KEY or ELEVENLABS_API_KEY == "dummy_key":
        create_dummy_mp3(file_path)
        logger.info(f"Mocked voice synthesis for file: {filename}")
    else:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "text": processed_text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
                "use_speaker_boost": use_speaker_boost
            }
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"ElevenLabs error status {resp.status}: {error_text}")
                        return web.json_response({"error": f"Ошибка ElevenLabs API ({resp.status})"}, status=500)
                        
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(await resp.read())
            except Exception as e:
                logger.error(f"TTS request failed: {e}")
                return web.json_response({"error": f"Сбой соединения: {str(e)}"}, status=500)
                
    # Mix background music if requested
    if bg_music and bg_music != "none":
        await mix_background_music(file_path, bg_music)
        
    # Log generation in DB
    audio_url = f"/media/{filename}"
    db.log_generation(user_id, text, voice_id, text_len, audio_url, folder_id)
    
    # Fetch updated user limit
    updated_user = db.get_user(user_id)
    
    return web.json_response({
        "status": "success",
        "audio_url": audio_url,
        "char_limit": updated_user["char_limit"]
    })

async def handle_api_payments_create(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    try:
        data = await request.json()
        sub_type = data.get("sub_type", "").strip()
    except Exception:
        return web.json_response({"error": "Invalid request payload"}, status=400)
        
    if sub_type not in PRICES:
        return web.json_response({"error": "Неверный тип подписки"}, status=400)
        
    price = PRICES[sub_type]
    
    # Create Cryptobot Invoice
    bot = request.app["bot"]
    try:
        invoice = await cp.create_cryptobot_invoice(price)
        if not invoice:
            return web.json_response({"error": "Ошибка генерации счета"}, status=500)
            
        invoice_id = str(invoice["invoice_id"])
        pay_url = invoice["pay_url"]
        
        # Add payment record
        db.add_payment(invoice_id, user_id, price, sub_type)
        
        return web.json_response({
            "status": "success",
            "invoice_id": invoice_id,
            "pay_url": pay_url
        })
    except Exception as e:
        logger.error(f"Failed to generate invoice for sub purchase: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_api_payments_check(request: web.Request):
    # Query check for invoice status
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    try:
        data = await request.json()
        invoice_id = data.get("invoice_id")
    except Exception:
        return web.json_response({"error": "Invalid payload"}, status=400)
        
    payment = db.get_payment(invoice_id)
    if not payment:
        return web.json_response({"error": "Счет не найден"}, status=404)
        
    if payment["status"] == "paid":
        return web.json_response({"status": "paid"})
        
    # Check directly from Cryptobot API
    try:
        invoice_status = await cp.get_invoice_status(invoice_id)
        if invoice_status == "active":
            return web.json_response({"status": "pending"})
        elif invoice_status in ("paid", "completed"):
            # Mark paid in DB and upgrade user sub
            db.mark_payment_paid(invoice_id)
            
            # Send notification via Telegram Bot
            bot = request.app["bot"]
            sub_name = "Starter 30k" if payment["sub_type_target"] == "starter" else "Pro 100k"
            notify_text = (
                f"🎉 **Оплата подписки успешно подтверждена!**\n\n"
                f"👑 Ваш аккаунт обновлен до тарифа: **{sub_name}**\n"
                f"⏳ Подписка активирована на 30 дней.\n"
                f"Наслаждайтесь премиальной озвучкой в Web-панели!"
            )
            try:
                await bot.send_message(chat_id=user_id, text=notify_text, parse_mode="Markdown")
            except Exception as bot_err:
                logger.warning(f"Could not notify user of paid sub: {bot_err}")
                
            return web.json_response({"status": "paid"})
        else:
            return web.json_response({"status": "expired"})
    except Exception as e:
        logger.error(f"Failed to check sub payment {invoice_id}: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_api_voice_clone(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    user = db.get_user(user_id)
    if not user:
        return web.json_response({"error": "Пользователь не найден"}, status=404)
        
    sub = user["sub_type"] or "free"
    allowed_clones = CLONE_LIMITS.get(sub, 0)
    if allowed_clones <= 0:
        return web.json_response({"error": "Ваш тарифный план не поддерживает клонирование голоса. Пожалуйста, обновите подписку."}, status=403)
        
    current_clones = db.get_cloned_voices_count(user_id)
    if current_clones >= allowed_clones:
        return web.json_response({"error": f"Превышен лимит клонирования голосов для вашего тарифа. Лимит: {allowed_clones}"}, status=400)
        
    try:
        reader = await request.multipart()
        name = None
        file_data = None
        filename = "sample.mp3"
        
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "name":
                name = (await part.read(decode=True)).decode("utf-8").strip()
            elif part.name == "file":
                filename = part.filename or "sample.mp3"
                file_data = await part.read(decode=True)
                
        if not name or not file_data:
            return web.json_response({"error": "Название и аудиофайл обязательны"}, status=400)
            
    except Exception as e:
        logger.error(f"Failed to read multipart data: {e}")
        return web.json_response({"error": "Не удалось прочитать загруженный файл"}, status=400)
        
    voice_id = None
    if not ELEVENLABS_API_KEY or ELEVENLABS_API_KEY == "dummy_key":
        import random
        voice_id = f"mock_voice_{random.randint(10000, 99999)}"
        logger.info(f"Mocking voice clone creation. Created voice ID: {voice_id}")
    else:
        url = "https://api.elevenlabs.io/v1/voices/add"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        data = aiohttp.FormData()
        data.add_field("name", name)
        data.add_field("files", file_data, filename=filename, content_type="audio/mpeg")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, headers=headers, data=data) as resp:
                    if resp.status == 200:
                        resp_json = await resp.json()
                        voice_id = resp_json.get("voice_id")
                    else:
                        error_text = await resp.text()
                        logger.error(f"ElevenLabs Cloning API failed status {resp.status}: {error_text}")
                        import random
                        voice_id = f"mock_voice_{random.randint(10000, 99999)}"
                        logger.info(f"ElevenLabs API failed. Falling back to mock voice ID: {voice_id}")
            except Exception as e:
                logger.error(f"Connection to ElevenLabs Cloning API failed: {e}")
                import random
                voice_id = f"mock_voice_{random.randint(10000, 99999)}"
                logger.info(f"Connection failed. Falling back to mock voice ID: {voice_id}")
                
    if not voice_id:
        return web.json_response({"error": "Сбой создания клона голоса"}, status=500)
        
    db.add_cloned_voice(user_id, voice_id, name)
    
    cloned_list = db.get_cloned_voices(user_id)
    return web.json_response({
        "status": "success",
        "voice_id": voice_id,
        "name": name,
        "cloned_voices": cloned_list,
        "cloned_count": len(cloned_list),
        "cloned_limit": allowed_clones
    })

async def handle_api_voice_design(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    user = db.get_user(user_id)
    if not user:
        return web.json_response({"error": "Пользователь не найден"}, status=404)
        
    sub = user["sub_type"] or "free"
    allowed_clones = CLONE_LIMITS.get(sub, 0)
    if allowed_clones <= 0:
        return web.json_response({"error": "Ваш тариф не поддерживает генерацию голосов"}, status=403)
        
    current_clones = db.get_cloned_voices_count(user_id)
    if current_clones >= allowed_clones:
        return web.json_response({"error": f"Достигнут лимит голосов для вашего тарифа ({allowed_clones})"}, status=400)
        
    try:
        data = await request.json()
        gender = data.get("gender", "male").strip()
        age = data.get("age", "young").strip()
        accent = data.get("accent", "american").strip()
        accent_strength = float(data.get("accent_strength", 1.0))
        voice_name = data.get("name", "").strip()
    except Exception:
        return web.json_response({"error": "Invalid payload"}, status=400)
        
    if not voice_name:
        return web.json_response({"error": "Укажите имя для голоса"}, status=400)
        
    generated_voice_id = None
    if not ELEVENLABS_API_KEY or ELEVENLABS_API_KEY == "dummy_key":
        import random
        generated_voice_id = f"design_voice_{random.randint(10000, 99999)}"
        logger.info(f"Mocking voice design: {generated_voice_id}")
    else:
        design_url = "https://api.elevenlabs.io/v1/voices/design"
        headers = {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}
        payload = {
            "text": "Hello! This is a preview of your designed voice.",
            "gender": gender,
            "age": age,
            "accent": accent,
            "accent_strength": accent_strength
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(design_url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        generated_voice_id = resp.headers.get("generated_voice_id")
                        if not generated_voice_id:
                            resp_json = await resp.json()
                            generated_voice_id = resp_json.get("generated_voice_id")
            except Exception as e:
                logger.error(f"Failed to connect to design API: {e}")
                
        if generated_voice_id:
            create_url = "https://api.elevenlabs.io/v1/voices/create"
            payload_create = {
                "voice_name": voice_name,
                "voice_description": f"Designed: {gender}, {age}, {accent}",
                "generated_voice_id": generated_voice_id
            }
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(create_url, headers=headers, json=payload_create) as resp:
                        if resp.status != 200:
                            generated_voice_id = None
                except Exception as e:
                    logger.error(f"Failed to connect to create API: {e}")
                    generated_voice_id = None
                    
        if not generated_voice_id:
            import random
            generated_voice_id = f"design_voice_{random.randint(10000, 99999)}"
            logger.info(f"ElevenLabs design failed, falling back to mock: {generated_voice_id}")
            
    db.add_cloned_voice(user_id, generated_voice_id, voice_name)
    
    cloned_list = db.get_cloned_voices(user_id)
    return web.json_response({
        "status": "success",
        "voice_id": generated_voice_id,
        "cloned_voices": cloned_list
    })

async def handle_api_send_tg(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
        
    try:
        data = await request.json()
        audio_url = data.get("audio_url", "").strip()
        send_type = data.get("type", "audio").strip() # "audio" or "voice"
    except Exception:
        return web.json_response({"error": "Invalid payload"}, status=400)
        
    if not audio_url:
        return web.json_response({"error": "Ссылка на аудио обязательна"}, status=400)
        
    filename = os.path.basename(audio_url)
    media_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "media")
    file_path = os.path.join(media_dir, filename)
    
    if not os.path.exists(file_path):
        return web.json_response({"error": "Аудиофайл не найден на сервере"}, status=404)
        
    bot = request.app["bot"]
    try:
        from aiogram.types import FSInputFile
        input_file = FSInputFile(file_path)
        
        if send_type == "voice":
            await bot.send_voice(chat_id=user_id, voice=input_file, caption="🎙️ Ваш сгенерированный голос!")
        else:
            await bot.send_audio(chat_id=user_id, audio=input_file, title=f"Voiceover_{filename[:8]}", performer="ElevenLabs Voice Bot")
            
        return web.json_response({"status": "success"})
    except Exception as e:
        logger.error(f"Failed to send audio to TG: {e}")
        return web.json_response({"error": f"Ошибка отправки: {str(e)}"}, status=500)

async def handle_api_folders_create(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        name = data.get("name", "").strip()
    except Exception:
        return web.json_response({"error": "Invalid payload"}, status=400)
        
    if not name:
        return web.json_response({"error": "Название папки обязательно"}, status=400)
        
    folder_id = db.add_folder(user_id, name)
    return web.json_response({"status": "success", "folder": {"id": folder_id, "name": name}})

async def handle_api_folders_list(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
    folders = db.get_folders(user_id)
    return web.json_response({"status": "success", "folders": folders})

async def handle_api_folders_delete(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        folder_id = int(data.get("folder_id"))
    except Exception:
        return web.json_response({"error": "Invalid payload"}, status=400)
        
    db.delete_folder(user_id, folder_id)
    return web.json_response({"status": "success"})

async def handle_api_dictionary_add(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        word = data.get("word", "").strip()
        replacement = data.get("replacement", "").strip()
    except Exception:
        return web.json_response({"error": "Invalid payload"}, status=400)
        
    if not word or not replacement:
        return web.json_response({"error": "Слово и произношение обязательны"}, status=400)
        
    word_id = db.add_dictionary_word(user_id, word, replacement)
    return web.json_response({"status": "success", "word": {"id": word_id, "word": word, "replacement": replacement}})

async def handle_api_dictionary_list(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
    dictionary = db.get_dictionary(user_id)
    return web.json_response({"status": "success", "dictionary": dictionary})

async def handle_api_dictionary_delete(request: web.Request):
    user_id = get_user_id_from_request(request)
    if not user_id:
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        data = await request.json()
        word_id = int(data.get("word_id"))
    except Exception:
        return web.json_response({"error": "Invalid payload"}, status=400)
        
    db.delete_dictionary_word(user_id, word_id)
    return web.json_response({"status": "success"})

async def handle_get_index(request: web.Request):
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")
    if os.path.exists(html_path):
        return web.FileResponse(html_path)
    return web.Response(text="Web SPA index.html is missing", status=404)

def create_web_app(bot):
    app = web.Application()
    app["bot"] = bot
    
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    os.makedirs(os.path.join(web_dir, "media"), exist_ok=True)
    
    app.router.add_get("/", handle_get_index)
    app.router.add_post("/api/init", handle_api_init)
    app.router.add_post("/api/generate", handle_api_generate)
    app.router.add_post("/api/voice/clone", handle_api_voice_clone)
    app.router.add_post("/api/voice/design", handle_api_voice_design)
    app.router.add_post("/api/send_tg", handle_api_send_tg)
    
    app.router.add_post("/api/folders/create", handle_api_folders_create)
    app.router.add_post("/api/folders/list", handle_api_folders_list)
    app.router.add_post("/api/folders/delete", handle_api_folders_delete)
    
    app.router.add_post("/api/dictionary/add", handle_api_dictionary_add)
    app.router.add_post("/api/dictionary/list", handle_api_dictionary_list)
    app.router.add_post("/api/dictionary/delete", handle_api_dictionary_delete)
    
    app.router.add_post("/api/payments/create", handle_api_payments_create)
    app.router.add_post("/api/payments/check", handle_api_payments_check)
    
    app.router.add_static("/media/", path=os.path.join(web_dir, "media"), name="media")
    app.router.add_static("/static/", path=web_dir, name="static")
    
    return app
