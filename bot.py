from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    ContextTypes, filters, ChatMemberHandler
)
from datetime import datetime, timedelta
import sqlite3
import os
import logging

# ---------- CONFIG ----------
TOKEN = os.getenv("TOKEN")
INACTIVITY_DAYS = 14
NEW_USER_GRACE_DAYS = 3

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO
)

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

# ---------- REGISTER ACTIVITY ----------
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
    DO UPDATE SET last_activity=excluded.last_activity,
                  warned=0
    """, (chat.id, user.id, now().isoformat(), now().isoformat()))
    conn.commit()

# ---------- REGISTER JOIN ----------
async def track_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    member = update.chat_member
    user = member.new_chat_member.user

    # Solo cuando entra un usuario (no admins que cambian estado)
    if member.old_chat_member.status in ["left", "kicked"] and member.new_chat_member.status == "member":
        cur.execute("""
        INSERT OR IGNORE INTO users (chat_id, user_id, last_activity, joined_at, warned)
        VALUES (?, ?, ?, ?, 0)
        """, (chat.id, user.id, now().isoformat(), now().isoformat()))
        conn.commit()

# ---------- CHECK INACTIVES ----------
async def check_inactives(context: ContextTypes.DEFAULT_TYPE):
    limit = now() - timedelta(days=INACTIVITY_DAYS)
    grace = now() - timedelta(days=NEW_USER_GRACE_DAYS)

    cur.execute("SELECT chat_id, user_id, last_activity, joined_at, warned FROM users")
    rows = cur.fetchall()

    for chat_id, user_id, last_activity, joined_at, warned in rows:
        try:
            last_dt = datetime.fromisoformat(last_activity)
            joined_dt = datetime.fromisoformat(joined_at)
        except Exception as e:
            logging.warning(f"Formato de fecha incorrecto para {user_id}: {e}")
            continue

        if warned:
            continue
        if joined_dt > grace:
            continue
        if last_dt >= limit:
            continue

        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in ["administrator", "creator"]:
                continue

            # Mensaje privado
            try:
                await context.bot.send_message(
                    user_id,
                    f"⚠️ Hola, llevas {INACTIVITY_DAYS} días sin participar en el grupo."
                )
            except Exception as e:
                logging.warning(f"No se pudo enviar mensaje a {user_id}: {e}")

            # Aviso en grupo
            await context.bot.send_message(
                chat_id,
                f"⚠️ Usuario inactivo detectado: <a href='tg://user?id={user_id}'>usuario</a>",
                parse_mode="HTML"
            )

            # Marcar como avisado
            cur.execute("""
            UPDATE users SET warned=1 WHERE chat_id=? AND user_id=?
            """, (chat_id, user_id))
            conn.commit()
        except Exception as e:
            logging.warning(f"Error al procesar usuario {user_id} en chat {chat_id}: {e}")

# ---------- COMMANDS ----------
async def inactive_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user_id = update.effective_user.id
    member = await chat.get_member(user_id)

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

# Handlers
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, register_activity))
app.add_handler(ChatMemberHandler(track_new_member, ChatMemberHandler.CHAT_MEMBER))
app.add_handler(CommandHandler("inactivos", inactive_list))

# Jobs
app.job_queue.run_repeating(check_inactives, interval=86400, first=10)

print("Bot de inactivos activo")
app.run_polling()
