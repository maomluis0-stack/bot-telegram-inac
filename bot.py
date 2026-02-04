from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    ContextTypes, filters
)
from datetime import datetime, timedelta
import sqlite3
import os

# TOKEN desde variable de entorno
TOKEN = os.getenv("TOKEN")

INACTIVITY_DAYS = 14
NEW_USER_GRACE_DAYS = 3   # usuarios nuevos ignorados

# ---------- DB ----------
conn = sqlite3.connect("activity.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER,
    user_id INTEGER,
    last_activity TEXT,
    joined_at TEXT,
    warned INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
)
""")
conn.commit()

# ---------- HELPERS ----------
def now():
    return datetime.utcnow()

# ---------- ACTIVITY ----------
async def register_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user:
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ["group", "supergroup"]:
        return

    cur.execute("""
    INSERT INTO users (chat_id, user_id, last_activity, joined_at, warned)
    VALUES (?, ?, ?, ?, 0)
    ON CONFLICT(chat_id, user_id)
    DO UPDATE SET last_activity=excluded.last_activity
    """, (chat.id, user.id, now().isoformat(), now().isoformat()))
    conn.commit()

# ---------- CHECK INACTIVES ----------
async def check_inactives(context: ContextTypes.DEFAULT_TYPE):
    limit = now() - timedelta(days=INACTIVITY_DAYS)
    grace = now() - timedelta(days=NEW_USER_GRACE_DAYS)

    cur.execute("SELECT chat_id, user_id, last_activity, joined_at, warned FROM users")
    rows = cur.fetchall()

    for chat_id, user_id, last_activity, joined_at, warned in rows:
        if warned:
            continue

        if datetime.fromisoformat(joined_at) > grace:
            continue

        if datetime.fromisoformat(last_activity) < limit:
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
                if member.status in ["administrator", "creator"]:
                    continue

                # Aviso privado
                await context.bot.send_message(
                    user_id,
                    f"⚠️ Hola, llevas {INACTIVITY_DAYS} días sin participar en el grupo."
                )

                # Aviso en grupo
                await context.bot.send_message(
                    chat_id,
                    f"⚠️ Usuario inactivo detectado: <a href='tg://user?id={user_id}'>usuario</a>",
                    parse_mode="HTML"
                )

                # Marcar como avisado
                cur.execute("""
                UPDATE users SET warned=1
                WHERE chat_id=? AND user_id=?
                """, (chat_id, user_id))
                conn.commit()

            except:
                pass

# ---------- COMMANDS ----------
async def inactive_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    member = await chat.get_member(update.effective_user.id)

    if member.status not in ["administrator", "creator"]:
        return

    limit = now() - timedelta(days=INACTIVITY_DAYS)

    cur.execute("""
    SELECT user_id FROM users
    WHERE chat_id=? AND last_activity < ?
    """, (chat.id, limit.isoformat()))

    users = cur.fetchall()

    if not users:
        await update.message.reply_text("✅ No hay usuarios inactivos.")
        return

    text = "📋 Usuarios inactivos:\n"
    for (uid,) in users:
        text += f"• <a href='tg://user?id={uid}'>usuario</a>\n"

    await update.message.reply_text(text, parse_mode="HTML")

# ---------- APP ----------
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(MessageHandler(filters.ALL, register_activity))
app.add_handler(CommandHandler("inactivos", inactive_list))

app.job_queue.run_repeating(check_inactives, interval=86400, first=10)

print("Bot de inactivos activo")
app.run_polling()
