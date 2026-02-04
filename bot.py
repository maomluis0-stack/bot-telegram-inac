import os
import sqlite3
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)

# ===== VARIABLES DE ENTORNO =====
TOKEN = os.environ.get("BOT_TOKEN")
APP_URL = os.environ.get("APP_URL")
PORT = int(os.environ.get("PORT", 8080))

# ===== CONFIGURACIÓN POR DEFECTO =====
INACTIVO_DIAS_DEFECTO = 14
NUEVO_DIAS_DEFECTO = 3

# ===== BASE DE DATOS =====
db = sqlite3.connect("bot.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER,
    chat_id INTEGER,
    last_activity TEXT,
    join_date TEXT,
    PRIMARY KEY (user_id, chat_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS config (
    chat_id INTEGER PRIMARY KEY,
    inactive_days INTEGER,
    new_user_days INTEGER
)
""")

db.commit()


# ===== FUNCIONES =====
def obtener_config(chat_id):
    cur.execute("SELECT inactive_days, new_user_days FROM config WHERE chat_id=?", (chat_id,))
    row = cur.fetchone()
    if row:
        return row
    return INACTIVO_DIAS_DEFECTO, NUEVO_DIAS_DEFECTO


async def registrar_actividad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if not user or user.is_bot:
        return

    ahora = datetime.utcnow().isoformat()

    cur.execute("""
    INSERT INTO users (user_id, chat_id, last_activity, join_date)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(user_id, chat_id)
    DO UPDATE SET last_activity=?
    """, (user.id, chat.id, ahora, ahora, ahora))

    db.commit()


async def revisar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    ahora = datetime.utcnow()

    inactivo_dias, nuevo_dias = obtener_config(chat.id)

    admins = await chat.get_administrators()
    admins_ids = {a.user.id for a in admins}

    cur.execute("SELECT user_id, last_activity, join_date FROM users WHERE chat_id=?", (chat.id,))
    usuarios = cur.fetchall()

    avisados = 0

    for user_id, last_activity, join_date in usuarios:
        if user_id in admins_ids:
            continue

        if (ahora - datetime.fromisoformat(join_date)).days < nuevo_dias:
            continue

        if (ahora - datetime.fromisoformat(last_activity)).days >= inactivo_dias:
            await context.bot.send_message(
                chat.id,
                f"⚠️ <a href='tg://user?id={user_id}'>Usuario</a> inactivo {inactivo_dias} días.",
                parse_mode="HTML"
            )
            avisados += 1

    await update.message.reply_text(f"Revisión terminada. Avisos enviados: {avisados}")


async def set_inactivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dias = int(context.args[0])
    chat_id = update.effective_chat.id

    _, nuevo = obtener_config(chat_id)

    cur.execute("""
    INSERT INTO config (chat_id, inactive_days, new_user_days)
    VALUES (?, ?, ?)
    ON CONFLICT(chat_id)
    DO UPDATE SET inactive_days=?
    """, (chat_id, dias, nuevo, dias))

    db.commit()
    await update.message.reply_text(f"Inactividad configurada a {dias} días")


async def set_nuevo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dias = int(context.args[0])
    chat_id = update.effective_chat.id

    inactivo, _ = obtener_config(chat_id)

    cur.execute("""
    INSERT INTO config (chat_id, inactive_days, new_user_days)
    VALUES (?, ?, ?)
    ON CONFLICT(chat_id)
    DO UPDATE SET new_user_days=?
    """, (chat_id, inactivo, dias, dias))

    db.commit()
    await update.message.reply_text(f"Usuarios nuevos excluidos {dias} días")


# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_actividad))
    app.add_handler(CommandHandler("revisar", revisar))
    app.add_handler(CommandHandler("set_inactivo", set_inactivo))
    app.add_handler(CommandHandler("set_nuevo", set_nuevo))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{APP_URL}/{TOKEN}"
    )


if __name__ == "__main__":
    main()
