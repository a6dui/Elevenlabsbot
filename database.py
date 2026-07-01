import os
import sqlite3
import secrets
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_bot.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0.0,
        char_limit INTEGER DEFAULT 5000,
        sub_type TEXT DEFAULT 'free',
        sub_until TEXT DEFAULT NULL,
        api_key TEXT UNIQUE,
        registered_at TEXT
    )
    """)
    
    # Generations history table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS generations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        voice_id TEXT,
        chars_used INTEGER,
        audio_path TEXT,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (telegram_id)
    )
    """)
    
    # Payments table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        invoice_id TEXT PRIMARY KEY,
        user_id INTEGER,
        amount REAL,
        sub_type_target TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )
    """)
    
    # Cloned voices table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cloned_voices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        voice_id TEXT UNIQUE,
        name TEXT,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (telegram_id)
    )
    """)
    
    conn.commit()
    conn.close()

def create_user(telegram_id, username):
    conn = get_db_connection()
    cursor = conn.cursor()
    user = cursor.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not user:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO users (telegram_id, username, char_limit, sub_type, registered_at) VALUES (?, ?, 5000, 'free', ?)",
            (telegram_id, username, now)
        )
        conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_api_key(api_key):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE api_key = ?", (api_key,)).fetchone()
    conn.close()
    return dict(user) if user else None

def generate_api_key(telegram_id):
    api_key = f"zk_voice_{secrets.token_hex(16)}"
    conn = get_db_connection()
    conn.execute("UPDATE users SET api_key = ? WHERE telegram_id = ?", (api_key, telegram_id))
    conn.commit()
    conn.close()
    return api_key

def update_balance(telegram_id, amount):
    conn = get_db_connection()
    conn.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, telegram_id))
    conn.commit()
    conn.close()

def upgrade_subscription(telegram_id, sub_type):
    conn = get_db_connection()
    now = datetime.now()
    until = (now + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Limits mapping for Starter, Creator, Pro, Scale, Business
    limits = {
        'free': 5000,
        'starter': 30000,
        'creator': 100000,
        'pro': 250000,
        'scale': 500000,
        'business': 1000000
    }
    
    char_limit = limits.get(sub_type, 5000)
    if sub_type == 'free':
        until = None
        
    conn.execute(
        "UPDATE users SET sub_type = ?, sub_until = ?, char_limit = ? WHERE telegram_id = ?",
        (sub_type, until, char_limit, telegram_id)
    )
    conn.commit()
    conn.close()

def log_generation(telegram_id, text, voice_id, chars_used, audio_path):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Record generation
    cursor.execute(
        "INSERT INTO generations (user_id, text, voice_id, chars_used, audio_path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (telegram_id, text, voice_id, chars_used, audio_path, now)
    )
    
    # Deduct character limit
    cursor.execute(
        "UPDATE users SET char_limit = MAX(0, char_limit - ?) WHERE telegram_id = ?",
        (chars_used, telegram_id)
    )
    
    conn.commit()
    conn.close()

def get_user_generations(telegram_id, limit=30):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM generations WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (telegram_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_payment(invoice_id, telegram_id, amount, sub_type_target):
    conn = get_db_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO payments (invoice_id, user_id, amount, sub_type_target, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
        (invoice_id, telegram_id, amount, sub_type_target, now)
    )
    conn.commit()
    conn.close()

def get_payment(invoice_id):
    conn = get_db_connection()
    pay = conn.execute("SELECT * FROM payments WHERE invoice_id = ?", (invoice_id,)).fetchone()
    conn.close()
    return dict(pay) if pay else None

def mark_payment_paid(invoice_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    pay = cursor.execute("SELECT * FROM payments WHERE invoice_id = ? AND status = 'pending'", (invoice_id,)).fetchone()
    if pay:
        cursor.execute("UPDATE payments SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
        conn.commit()
        conn.close()
        upgrade_subscription(pay["user_id"], pay["sub_type_target"])
        return pay["user_id"]
    conn.close()
    return None

def add_cloned_voice(telegram_id, voice_id, name):
    conn = get_db_connection()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    success = False
    try:
        conn.execute(
            "INSERT INTO cloned_voices (user_id, voice_id, name, created_at) VALUES (?, ?, ?, ?)",
            (telegram_id, voice_id, name, now)
        )
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def get_cloned_voices(telegram_id):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM cloned_voices WHERE user_id = ? ORDER BY id DESC", (telegram_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_cloned_voices_count(telegram_id):
    conn = get_db_connection()
    row = conn.execute("SELECT COUNT(*) FROM cloned_voices WHERE user_id = ?", (telegram_id,)).fetchone()
    count = row[0] if row else 0
    conn.close()
    return count
