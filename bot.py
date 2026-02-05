import os
import sqlite3
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

TOKEN = os.environ.get("8509975594:AAGpgppX7aAzuSYIug0udL3MZmuYyNhGS20")

DB_FILE = "users.db"
INACTIVITY_DAYS = 14


# ------------------ BASE DE DATOS ------------------

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            last_message TEXT
        )
    """)
    conn.commit()
    conn.close()


def update_user(user_id, username):
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username, last_message)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET last_message=excluded.last_message,
                      username=excluded.username
    """, (user_id, username, now))
    conn.commit()
    conn.close()


def get_inactive_users():
    limit_date = datetime.utcnow() - timedelta(days=INACTIVITY_DAYS)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, last_message FROM users")
    rows = cursor.fetchall()
    conn.close()

    inactive = []
    for user_id, username, last_message in rows:
        last = datetime.fromisoformat(last_message)
        if last < limit_date:
            inactive.append((user_id, username))
    return inactive


# ------------------ HANDLERS ------------------

async def track_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.from_user:
        user = update.message.from_user
        update_user(
            user.id,
            user.username or user.full_name
        )


async def scan_inactives(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inactive = get_inactive_users()

    if not inactive:
        await update.message.reply_text(
            "✅ No hay usuarios inactivos por más de 14 días."
        )
        return

    text = "⚠️ *Usuarios inactivos (+14 días):*\n\n"
    for user_id, username in inactive:
        if username:
            text += f"• @{username}\n"
        else:
            text += f"• ID: `{user_id}`\n"

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    conn.close()

    await update.message.reply_text(
        f"📊 Usuarios monitoreados: {total}"
    )


async def reset_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /reset @usuario")
        return

    username = context.args[0].replace("@", "")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users
        SET last_message=?
        WHERE username=?
    """, (datetime.utcnow().isoformat(), username))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🔄 Contador reiniciado para @{username}"
    )


# ------------------ MAIN ------------------

def main():
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_messages))
    app.add_handler(CommandHandler("scan", scan_inactives))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reset", reset_user))

    app.run_polling()


if __name__ == "__main__":
    main()
