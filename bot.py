import os
import psycopg2
from datetime import datetime, timedelta
import dateparser

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)

# ================= DATABASE =================
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    nama TEXT,
    kategori TEXT,
    deadline TIMESTAMP,
    reminder_days INTEGER,
    repeat TEXT,
    chat_id BIGINT,
    creator TEXT
)
""")
conn.commit()

# ================= STATE =================
user_state = {}

# ================= HELPER =================
def parse_waktu(text, kategori):
    dt = dateparser.parse(text, languages=['id'])

    if dt:
        if dt.hour == 0 and dt.minute == 0:
            if kategori == "kuliah":
                dt = dt.replace(hour=23, minute=59)
            else:
                dt = dt.replace(hour=19, minute=0)

    return dt

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Tambah", callback_data="tambah")],
        [InlineKeyboardButton("📋 List", callback_data="list")],
        [InlineKeyboardButton("✏️ Edit", callback_data="edit")],
        [InlineKeyboardButton("❌ Hapus", callback_data="hapus")]
    ]
    await update.message.reply_text("Menu:", reply_markup=InlineKeyboardMarkup(keyboard))

# ================= BUTTON =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "tambah":
        user_state[user_id] = {"step": "nama"}
        await query.message.reply_text("Nama tugas:")

    elif query.data == "list":
        await list_tugas(update, context)

    elif query.data == "hapus":
        await list_tugas(update, context)
        user_state[user_id] = {"step": "hapus"}
        await query.message.reply_text("Nomor yang dihapus:")

    elif query.data == "edit":
        await list_tugas(update, context)
        user_state[user_id] = {"step": "edit_pilih"}
        await query.message.reply_text("Nomor yang ingin diedit:")

    elif query.data.startswith("kat_"):
        kategori = query.data.split("_")[1]
        user_state[user_id]["kategori"] = kategori
        user_state[user_id]["step"] = "deadline"
        await query.message.reply_text("Waktu (contoh: besok / 4 april 2026):")

# ================= HANDLE INPUT =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    if user_id not in user_state:
        return

    state = user_state[user_id]

    if state["step"] == "nama":
        state["nama"] = text
        state["step"] = "kategori"

        keyboard = [
            [InlineKeyboardButton("Kuliah", callback_data="kat_kuliah")],
            [InlineKeyboardButton("Organisasi", callback_data="kat_organisasi")]
        ]
        await update.message.reply_text("Kategori:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif state["step"] == "deadline":
        dt = parse_waktu(text, state["kategori"])

        if not dt:
            await update.message.reply_text("Format waktu tidak dikenali")
            return

        state["deadline"] = dt
        state["step"] = "reminder"
        await update.message.reply_text("Reminder (hari sebelum, kosong=1):")

    elif state["step"] == "reminder":
        try:
            reminder = int(text) if text else 1
        except:
            reminder = 1

        state["reminder"] = reminder
        state["step"] = "repeat"
        await update.message.reply_text("Repeat? (tidak / harian)")

    elif state["step"] == "repeat":
        repeat = text.lower()

        nama = state["nama"]
        kategori = state["kategori"]
        deadline = state["deadline"]
        reminder = state["reminder"]
        chat_id = update.effective_chat.id
        creator = update.effective_user.first_name

        cursor.execute(
            "INSERT INTO tasks (nama,kategori,deadline,reminder_days,repeat,chat_id,creator) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (nama, kategori, deadline, reminder, repeat, chat_id, creator)
        )
        conn.commit()

        schedule_reminders(context, nama, kategori, deadline, reminder, repeat, chat_id)

        await update.message.reply_text(f"Tugas ditambahkan oleh {creator}")
        user_state.pop(user_id)

# ================= REMINDER =================
def schedule_reminders(context, nama, kategori, deadline, reminder, repeat, chat_id):
    for d in list(set([reminder, 1, 0])):
        reminder_time = deadline - timedelta(days=d)
        delay = (reminder_time - datetime.now()).total_seconds()

        if delay > 0:
            context.job_queue.run_once(
                kirim_reminder,
                delay,
                data={"nama": nama, "kategori": kategori, "hari": d, "repeat": repeat},
                chat_id=chat_id
            )

async def kirim_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data

    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"Reminder H-{data['hari']}!\n{data['nama']} ({data['kategori']})"
    )

    if data["repeat"] == "harian":
        context.job_queue.run_once(
            kirim_reminder,
            86400,
            data=data,
            chat_id=context.job.chat_id
        )

# ================= LIST =================
async def list_tugas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    cursor.execute(
        "SELECT nama,kategori,deadline,creator FROM tasks WHERE chat_id=%s ORDER BY deadline ASC",
        (chat_id,)
    )
    rows = cursor.fetchall()

    if not rows:
        text = "Tidak ada tugas"
    else:
        text = ""
        for i, r in enumerate(rows):
            text += f"{i+1}. {r[0]} ({r[1]})\n{r[2]}\nBy: {r[3]}\n\n"

    if update.callback_query:
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)

# ================= MAIN =================
print("Bot aktif (PostgreSQL)...")

TOKEN = os.getenv("8617978089:AAGP44H_kMftgJrvmJyPnEYeqUA4dzmMjMQ")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("list", list_tugas))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

app.run_polling()