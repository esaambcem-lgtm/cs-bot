import os
import json
import logging
import random
import re
import sqlite3
import subprocess
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
FAST_MODEL = "llama-3.1-8b-instant"

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is not set")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =======================
# قاعدة البيانات
# =======================

def init_db():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        join_date TEXT,
        lang TEXT DEFAULT 'ar'
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS progress (
        user_id INTEGER,
        topic TEXT,
        count INTEGER DEFAULT 0,
        last_activity TEXT,
        PRIMARY KEY (user_id, topic)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS quiz_stats (
        user_id INTEGER PRIMARY KEY,
        total_questions INTEGER DEFAULT 0,
        correct_answers INTEGER DEFAULT 0,
        streak INTEGER DEFAULT 0,
        best_streak INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS saved_answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        content TEXT,
        saved_date TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS flashcards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        question TEXT,
        answer TEXT,
        topic TEXT,
        reviews INTEGER DEFAULT 0,
        correct INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER PRIMARY KEY,
        level TEXT DEFAULT 'beginner',
        language TEXT DEFAULT 'ar',
        preferred_topic TEXT DEFAULT 'general'
    )
    """)

    conn.commit()
    conn.close()


def get_db():
    return sqlite3.connect("bot_data.db")


def register_user(user_id: int, username: str, first_name: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    INSERT OR IGNORE INTO users (user_id, username, first_name, join_date)
    VALUES (?, ?, ?, ?)
    """, (user_id, username, first_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def update_progress(user_id: int, topic: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    INSERT INTO progress (user_id, topic, count, last_activity)
    VALUES (?, ?, 1, ?)
    ON CONFLICT(user_id, topic) DO UPDATE SET
        count = count + 1,
        last_activity = ?
    """, (user_id, topic, datetime.now().isoformat(), datetime.now().isoformat()))
    conn.commit()
    conn.close()


def update_quiz_stats(user_id: int, correct: bool):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    INSERT INTO quiz_stats (user_id, total_questions, correct_answers, streak, best_streak)
    VALUES (?, 1, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
        total_questions = total_questions + 1,
        correct_answers = correct_answers + ?,
        streak = CASE WHEN ? THEN streak + 1 ELSE 0 END,
        best_streak = CASE WHEN ? THEN MAX(best_streak, streak + 1) ELSE best_streak END
    """, (
        user_id,
        1 if correct else 0,
        1 if correct else 0,
        0,
        1 if correct else 0,
        correct,
        correct,
    ))
    conn.commit()
    conn.close()


def save_answer(user_id: int, title: str, content: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    INSERT INTO saved_answers (user_id, title, content, saved_date)
    VALUES (?, ?, ?, ?)
    """, (user_id, title[:50], content[:2000], datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_saved_answers(user_id: int) -> List[tuple]:
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    SELECT id, title, saved_date
    FROM saved_answers
    WHERE user_id = ?
    ORDER BY saved_date DESC
    LIMIT 10
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def save_flashcard(user_id: int, question: str, answer: str, topic: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    INSERT INTO flashcards (user_id, question, answer, topic)
    VALUES (?, ?, ?, ?)
    """, (user_id, question, answer, topic))
    conn.commit()
    conn.close()


def get_flashcard_count(user_id: int) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM flashcards WHERE user_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count


def get_random_flashcard(user_id: int) -> Optional[tuple]:
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    SELECT id, question, answer
    FROM flashcards
    WHERE user_id = ?
    ORDER BY RANDOM()
    LIMIT 1
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_user_stats(user_id: int) -> Dict[str, Any]:
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM quiz_stats WHERE user_id = ?", (user_id,))
    quiz = c.fetchone()

    c.execute("SELECT topic, count FROM progress WHERE user_id = ? ORDER BY count DESC LIMIT 5", (user_id,))
    topics = c.fetchall()

    c.execute("SELECT COUNT(*) FROM saved_answers WHERE user_id = ?", (user_id,))
    saved = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM flashcards WHERE user_id = ?", (user_id,))
    flashcards = c.fetchone()[0]

    conn.close()
    return {
        "quiz": quiz,
        "topics": topics,
        "saved": saved,
        "flashcards": flashcards,
    }


def set_user_setting(user_id: int, key: str, value: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    INSERT INTO user_settings (user_id, level, language, preferred_topic)
    VALUES (?, 'beginner', 'ar', 'general')
    ON CONFLICT(user_id) DO NOTHING
    """, (user_id,))
    if key == "level":
        c.execute("UPDATE user_settings SET level = ? WHERE user_id = ?", (value, user_id))
    elif key == "language":
        c.execute("UPDATE user_settings SET language = ? WHERE user_id = ?", (value, user_id))
    elif key == "preferred_topic":
        c.execute("UPDATE user_settings SET preferred_topic = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def get_user_setting(user_id: int, key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_db()
    c = conn.cursor()
    c.execute(f"SELECT {key} FROM user_settings WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else default


# =======================
# سجل المحادثة
# =======================

user_sessions: Dict[int, List[Dict[str, str]]] = {}


def get_user_history(user_id: int) -> List[Dict[str, str]]:
    if user_id not in user_sessions:
        user_sessions[user_id] = []
    return user_sessions[user_id][-12:]


def add_to_history(user_id: int, role: str, content: str):
    if user_id not in user_sessions:
        user_sessions[user_id] = []
    user_sessions[user_id].append({"role": role, "content": content})


# =======================
# Prompts
# =======================

CS_SYSTEM_PROMPT = """أنت مساعد ذكاء اصطناعي خبير في علوم الحاسوب للطلاب الجامعيين.
تتخصص في:
- البرمجة وتصحيح الأخطاء
- الخوارزميات وهياكل البيانات
- قواعد البيانات والـ SQL
- الشبكات
- الذكاء الاصطناعي
- الرياضيات المتقطعة
اكتب بالعربية، وكن موجزًا ومفيدًا."""

INTERVIEW_PROMPT = """أنت مُحاوِر تقني خبير.
ابدأ بسؤال واحد واضح، قيم الإجابة بصدق، وقدم تلميحات عند الحاجة."""


# =======================
# Groq API
# =======================

async def call_groq(messages: List[Dict[str, str]], model: str = None, max_tokens: int = 3000) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": max_tokens,
        "top_p": 0.9,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GROQ_API_URL, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    error_text = await response.text()
                    logger.error("Groq error: %s", error_text)
                    return f"⚠️ خطأ من Groq: {error_text[:200]}"
    except Exception as e:
        logger.error("API error: %s", e)
        return f"⚠️ خطأ: {str(e)}"


async def get_ai_response(user_message: str, user_id: int, system: str = None) -> str:
    messages = [{"role": "system", "content": system or CS_SYSTEM_PROMPT}]
    messages.extend(get_user_history(user_id))
    messages.append({"role": "user", "content": user_message})
    response = await call_groq(messages)
    add_to_history(user_id, "user", user_message)
    add_to_history(user_id, "assistant", response)
    return response


# =======================
# تنفيذ كود آمن (محدود)
# =======================

async def execute_code(code: str, language: str = "python") -> str:
    if language != "python":
        return "⚠️ يدعم Python فقط حاليا."

    blocked = [
        "import os", "import sys", "import subprocess", "import shutil",
        "import socket", "import requests", "exec(", "eval(", "__import__",
        "open(", "os.", "sys.", "subprocess.", "shutil.", "socket."
    ]

    lower_code = code.lower()
    for item in blocked:
        if item.lower() in lower_code:
            return f"⚠️ الكود يحتوي على أمر غير مسموح به: `{item}`"

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
        )
        os.unlink(tmp_path)

        output = ""
        if result.stdout:
            output += f"✅ النتيجة:\n```python\n{result.stdout[:1500]}\n```"
        if result.stderr:
            output += f"\n❌ الأخطاء:\n```python\n{result.stderr[:500]}\n```"

        return output or "✅ تم التنفيذ بنجاح بدون إخراج."
    except subprocess.TimeoutExpired:
        return "⏱️ انتهت مهلة التنفيذ (10 ثوانٍ)."
    except Exception as e:
        return f"❌ خطأ في التنفيذ: {str(e)}"


# =======================
# Quiz Generator
# =======================

async def generate_quiz(topic: str, user_id: int) -> Dict[str, Any]:
    prompt = f"""أنشئ سؤال اختيار متعدد واحد (MCQ) في موضوع: {topic}
أرجع JSON فقط:
{{
  "question": "السؤال هنا",
  "options": {{"A": "الخيار 1", "B": "الخيار 2", "C": "الخيار 3", "D": "الخيار 4"}},
  "correct": "A",
  "explanation": "شرح موجز"
}}"""
    messages = [
        {"role": "system", "content": "أنت منشئ أسئلة متخصص في علوم الحاسوب. أجب بـ JSON فقط."},
        {"role": "user", "content": prompt},
    ]
    response = await call_groq(messages, model=FAST_MODEL, max_tokens=700)
    try:
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        logger.error("Quiz parse error: %s", e)
    return {}


# =======================
# الواجهة
# =======================

def get_main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("💻 شرح كود", callback_data="explain_code"),
            InlineKeyboardButton("🔧 تصحيح أخطاء", callback_data="debug_code"),
        ],
        [
            InlineKeyboardButton("▶️ تنفيذ كود", callback_data="run_code"),
            InlineKeyboardButton("📝 كويز", callback_data="quiz_menu"),
        ],
        [
            InlineKeyboardButton("🎯 مقابلة", callback_data="interview_start"),
            InlineKeyboardButton("📋 خطة دراسية", callback_data="study_plan"),
        ],
        [
            InlineKeyboardButton("🃏 فلاش كاردز", callback_data="flashcard_menu"),
            InlineKeyboardButton("📈 إحصائياتي", callback_data="my_stats"),
        ],
        [
            InlineKeyboardButton("⭐ إجابات محفوظة", callback_data="saved_answers"),
            InlineKeyboardButton("❓ سؤال حر", callback_data="free_question"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 احفظ هذا الرد", callback_data="save_last")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])


async def send_long_message(message, text: str, reply_markup=None):
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for idx, part in enumerate(parts):
            if idx == len(parts) - 1:
                await message.reply_text(part, reply_markup=reply_markup)
            else:
                await message.reply_text(part)
    else:
        await message.reply_text(text, reply_markup=reply_markup)


# =======================
# أوامر البداية
# =======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "", user.first_name)
    text = f"""🎓 مرحبا {user.first_name}!

أنا مساعدك في علوم الحاسوب.
اختر من القائمة أو اكتب سؤالك مباشرة 👇"""
    await update.message.reply_text(text, reply_markup=get_main_menu())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
📖 الأوامر:
 /start - البداية
 /help - المساعدة
 /quiz - كويز
 /run - تنفيذ كود Python
 /interview - محاكاة مقابلة
 /plan - خطة دراسية
 /stats - الإحصائيات
 /saved - الإجابات المحفوظة
 /clear - مسح السجل
"""
    await update.message.reply_text(text, reply_markup=get_main_menu())


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = []
    await update.message.reply_text("🗑️ تم مسح سجل المحادثة.", reply_markup=get_main_menu())


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_stats(update.message, update.effective_user.id)


async def show_stats(message, user_id: int):
    stats = get_user_stats(user_id)
    quiz = stats["quiz"]
    accuracy = 0
    if quiz and quiz[1] > 0:
        accuracy = round((quiz[2] / quiz[1]) * 100)

    topics_text = ""
    for topic, count in stats["topics"]:
        topics_text += f"• {topic}: {count} مرة\n"

    text = f"""📈 إحصائياتك:
🎯 الكويز:
- إجمالي الأسئلة: {quiz[1] if quiz else 0}
- الإجابات الصحيحة: {quiz[2] if quiz else 0}
- الدقة: {accuracy}%
- أطول سلسلة: {quiz[4] if quiz else 0} 🔥

📚 أكثر الموضوعات:
{topics_text or 'لا يوجد نشاط بعد'}

💾 الإجابات المحفوظة: {stats['saved']}
🃏 الفلاش كاردز: {stats['flashcards']}"""
    await message.reply_text(text, reply_markup=get_main_menu())


async def saved_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_saved(update.message, update.effective_user.id)


async def show_saved(message, user_id: int):
    saved = get_saved_answers(user_id)
    if not saved:
        await message.reply_text("⭐ لا توجد إجابات محفوظة بعد.", reply_markup=get_main_menu())
        return

    keyboard = []
    for item in saved:
        keyboard.append([InlineKeyboardButton(f"⭐ {item[1]}", callback_data=f"view_saved_{item[0]}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])

    await message.reply_text("⭐ إجاباتك المحفوظة:", reply_markup=InlineKeyboardMarkup(keyboard))


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args) if context.args else "علوم الحاسوب العامة"
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    quiz_data = await generate_quiz(topic, update.effective_user.id)
    if not quiz_data:
        await update.message.reply_text("⚠️ حدث خطأ في توليد السؤال.", reply_markup=get_main_menu())
        return

    context.user_data["current_quiz"] = quiz_data
    context.user_data["quiz_topic"] = topic

    options_text = "\n".join([f"  {k}) {v}" for k, v in quiz_data.get("options", {}).items()])
    question_text = f"📝 كويز - {topic}\n\n❓ {quiz_data.get('question', '')}\n\n{options_text}"

    keyboard = []
    for opt in quiz_data.get("options", {}).keys():
        keyboard.append([InlineKeyboardButton(f"{opt}", callback_data=f"quiz_ans_{opt}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])

    await update.message.reply_text(question_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "run_code"
    await update.message.reply_text("▶️ أرسل كود Python الآن وسأشغله.", reply_markup=get_main_menu())


async def interview_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "interview"
    context.user_data["interview_history"] = []
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    messages = [
        {"role": "system", "content": INTERVIEW_PROMPT},
        {"role": "user", "content": "ابدأ المقابلة التقنية."},
    ]
    response = await call_groq(messages)
    context.user_data["interview_history"] = [{"role": "assistant", "content": response}]
    await update.message.reply_text(f"🎯 محاكاة مقابلة\n\n{response}", reply_markup=get_main_menu())


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "study_plan"
    await update.message.reply_text("📋 أخبرني عن مستواك، المواد، هدفك، والوقت المتاح يوميًا.", reply_markup=get_main_menu())


# =======================
# معالجة الرسائل
# =======================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text or ""
    user_id = update.effective_user.id

    if context.user_data.get("mode") == "run_code":
        context.user_data["mode"] = None
        code = user_message
        match = re.search(r"```(?:python)?\n?(.*?)```", user_message, re.DOTALL)
        if match:
            code = match.group(1)
        result = await execute_code(code)
        context.user_data["last_response"] = result
        context.user_data["last_code"] = code
        await update.message.reply_text(result, reply_markup=get_back_menu())
        return

    if context.user_data.get("mode") == "study_plan":
        context.user_data["mode"] = None
        prompt = f"أنشئ خطة دراسية مخصصة بناءً على هذه المعلومات:\n{user_message}"
        response = await get_ai_response(prompt, user_id)
        context.user_data["last_response"] = response
        update_progress(user_id, "خطة دراسية")
        await send_long_message(update.message, response, get_back_menu())
        return

    if context.user_data.get("mode") == "interview":
        history = context.user_data.get("interview_history", [])
        history.append({"role": "user", "content": user_message})
        messages = [{"role": "system", "content": INTERVIEW_PROMPT}]
        messages.extend(history[-8:])
        response = await call_groq(messages)
        history.append({"role": "assistant", "content": response})
        context.user_data["interview_history"] = history
        context.user_data["last_response"] = response
        await update.message.reply_text(response, reply_markup=get_main_menu())
        return

    if user_message.startswith("/"):
        return

    response = await get_ai_response(user_message, user_id)
    context.user_data["last_response"] = response
    update_progress(user_id, "سؤال حر")
    await send_long_message(update.message, response, get_back_menu())


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    user_id = update.effective_user.id
    file_name = document.file_name or ""

    if file_name.endswith((".py", ".cpp", ".java", ".js", ".c", ".ts", ".sql", ".txt", ".md")):
        try:
            file = await context.bot.get_file(document.file_id)
            content = await file.download_as_bytearray()
            code = content.decode("utf-8", errors="ignore")

            prompt = f"حلل هذا الكود من الملف '{file_name}':\n```{code[:3000]}```"
            response = await get_ai_response(prompt, user_id)
            context.user_data["last_response"] = response
            await send_long_message(update.message, response, get_back_menu())
        except Exception as e:
            await update.message.reply_text(f"⚠️ خطأ في قراءة الملف: {str(e)}")
    else:
        await update.message.reply_text("⚠️ صيغة غير مدعومة. جرّب .py أو .txt أو .cpp", reply_markup=get_main_menu())


# =======================
# معالجة الأزرار
# =======================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "main_menu":
        context.user_data["mode"] = None
        await query.edit_message_text("🎓 القائمة الرئيسية", reply_markup=get_main_menu())

    elif data == "quiz_menu":
        keyboard = [
            [InlineKeyboardButton("🔍 الخوارزميات", callback_data="quiz_algorithms")],
            [InlineKeyboardButton("🗄️ قواعد البيانات", callback_data="quiz_databases")],
            [InlineKeyboardButton("🌐 الشبكات", callback_data="quiz_networks")],
            [InlineKeyboardButton("🐍 Python", callback_data="quiz_python")],
            [InlineKeyboardButton("🔀 عشوائي", callback_data="quiz_random")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")],
        ]
        await query.edit_message_text("📝 اختر موضوع الكويز:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("quiz_") and not data.startswith("quiz_ans_"):
        topic_map = {
            "quiz_algorithms": "الخوارزميات وهياكل البيانات",
            "quiz_databases": "قواعد البيانات والـ SQL",
            "quiz_networks": "الشبكات",
            "quiz_python": "Python",
            "quiz_random": random.choice(["الخوارزميات", "قواعد البيانات", "الشبكات", "Python"]),
        }
        topic = topic_map.get(data, "علوم الحاسوب")
        context.user_data["quiz_topic"] = topic
        await query.edit_message_text(f"⏳ جاري توليد سؤال عن {topic}...")
        quiz_data = await generate_quiz(topic, user_id)
        if not quiz_data:
            await query.edit_message_text("⚠️ حدث خطأ في توليد السؤال.", reply_markup=get_main_menu())
            return
        context.user_data["current_quiz"] = quiz_data

        options_text = "\n".join([f"  {k}) {v}" for k, v in quiz_data.get("options", {}).items()])
        question_text = f"📝 كويز - {topic}\n\n❓ {quiz_data.get('question', '')}\n\n{options_text}"

        keyboard = []
        for opt in quiz_data.get("options", {}).keys():
            keyboard.append([InlineKeyboardButton(f"{opt}", callback_data=f"quiz_ans_{opt}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await query.edit_message_text(question_text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("quiz_ans_"):
        answer = data.replace("quiz_ans_", "")
        quiz_data = context.user_data.get("current_quiz", {})
        correct = quiz_data.get("correct", "")
        is_correct = answer == correct
        update_quiz_stats(user_id, is_correct)
        update_progress(user_id, "كويز")

        if is_correct:
            result = f"✅ إجابة صحيحة!\n\n💡 الشرح:\n{quiz_data.get('explanation', '')}"
        else:
            result = f"❌ إجابة خاطئة.\nالإجابة الصحيحة: {correct}\n\n💡 الشرح:\n{quiz_data.get('explanation', '')}"

        await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 سؤال آخر", callback_data="quiz_menu")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
        ]))

    elif data == "run_code":
        context.user_data["mode"] = "run_code"
        await query.edit_message_text("▶️ أرسل كود Python الآن وسأشغله.", reply_markup=get_main_menu())

    elif data == "interview_start":
        context.user_data["mode"] = "interview"
        context.user_data["interview_history"] = []
        await query.edit_message_text("⏳ جاري تحضير المقابلة...")
        messages = [
            {"role": "system", "content": INTERVIEW_PROMPT},
            {"role": "user", "content": "ابدأ المقابلة التق��ية."},
        ]
        response = await call_groq(messages)
        context.user_data["interview_history"] = [{"role": "assistant", "content": response}]
        await query.edit_message_text(f"🎯 محاكاة مقابلة\n\n{response}", reply_markup=get_main_menu())

    elif data == "study_plan":
        context.user_data["mode"] = "study_plan"
        await query.edit_message_text("📋 أخبرني عن مستواك، المواد، هدفك، والوقت المتاح يوميًا.", reply_markup=get_main_menu())

    elif data == "free_question":
        context.user_data["mode"] = "free"
        await query.edit_message_text("❓ اكتب أي سؤال وسأجيب عليه فورًا.", reply_markup=get_main_menu())

    elif data == "flashcard_menu":
        count = get_flashcard_count(user_id)
        keyboard = [
            [InlineKeyboardButton("➕ إنشاء فلاش كاردز", callback_data="create_flashcards")],
        ]
        if count > 0:
            keyboard.append([InlineKeyboardButton(f"📖 مراجعة ({count} بطاقة)", callback_data="review_flashcards")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])

        await query.edit_message_text(
            f"🃏 الفلاش كاردز\n\nعندك {count} بطاقة حالياً.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "create_flashcards":
        keyboard = [
            [InlineKeyboardButton("الخوارزميات", callback_data="fc_create_algorithms")],
            [InlineKeyboardButton("قواعد البيانات", callback_data="fc_create_databases")],
            [InlineKeyboardButton("Python", callback_data="fc_create_python")],
            [InlineKeyboardButton("الشبكات", callback_data="fc_create_networks")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="flashcard_menu")],
        ]
        await query.edit_message_text("🃏 اختر موضوع لإنشاء فلاش كاردز:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("fc_create_"):
        topic = data.replace("fc_create_", "")
        await query.edit_message_text(f"⏳ جاري إنشاء فلاش كاردز عن {topic}...")
        prompt = f"""أنشئ 5 فلاش كاردز تعليمية عن: {topic} في علوم الحاسوب
أجب بـ JSON فقط:
[
  {{"question": "سؤال 1", "answer": "إجابة 1"}},
  {{"question": "سؤال 2", "answer": "إجابة 2"}},
  {{"question": "سؤال 3", "answer": "إجابة 3"}},
  {{"question": "سؤال 4", "answer": "إجابة 4"}},
  {{"question": "سؤال 5", "answer": "إجابة 5"}}
]"""
        messages = [
            {"role": "system", "content": "أنشئ فلاش كاردز تعليمية. أجب بـ JSON array فقط."},
            {"role": "user", "content": prompt},
        ]
        response = await call_groq(messages, model=FAST_MODEL)
        try:
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                cards = json.loads(match.group(0))
                for card in cards:
                    save_flashcard(user_id, card["question"], card["answer"], topic)
                await query.edit_message_text(
                    f"✅ تم إنشاء {len(cards)} فلاش كاردز عن {topic}!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📖 ابدأ المراجعة", callback_data="review_flashcards")],
                        [InlineKeyboardButton("🔙 رجوع", callback_data="flashcard_menu")],
                    ])
                )
        except Exception:
            await query.edit_message_text("⚠️ حدث خطأ أثناء إنشاء البطاقة.", reply_markup=get_main_menu())

    elif data == "review_flashcards":
        card = get_random_flashcard(user_id)
        if not card:
            await query.edit_message_text("لا توجد بطاقات بعد. أنشئ أول بطاقات!", reply_markup=get_main_menu())
            return

        context.user_data["current_flashcard"] = card
        await query.edit_message_text(
            f"🃏 فلاش كارد\n\n❓ {card[1]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👁️ اكشف الإجابة", callback_data="reveal_flashcard")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="flashcard_menu")],
            ])
        )

    elif data == "reveal_flashcard":
        card = context.user_data.get("current_flashcard")
        if card:
            await query.edit_message_text(
                f"🃏 فلاش كارد\n\n❓ {card[1]}\n\n✅ الإجابة:\n{card[2]}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📖 بطاقة أخرى", callback_data="review_flashcards")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="flashcard_menu")],
                ])
            )

    elif data == "my_stats":
        await show_stats(query.message, user_id)

    elif data == "saved_answers":
        await show_saved(query.message, user_id)

    elif data == "explain_code":
        await query.edit_message_text("💻 أرسل الكود مباشرة وسأشرحه لك.", reply_markup=get_main_menu())

    elif data == "debug_code":
        await query.edit_message_text("🔧 أرسل الكود الذي فيه خطأ وسأساعدك في تصحيحه.", reply_markup=get_main_menu())

    elif data == "save_last":
        last = context.user_data.get("last_response", "")
        if last:
            save_answer(user_id, (last[:40] or "رد محفوظ").replace("\n", " "), last)
            await query.answer("✅ تم الحفظ", show_alert=False)
        else:
            await query.answer("لا يوجد رد لحفظه", show_alert=False)

    elif data.startswith("view_saved_"):
        save_id = data.replace("view_saved_", "")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT content FROM saved_answers WHERE id = ? AND user_id = ?", (save_id, user_id))
        result = c.fetchone()
        conn.close()
        if result:
            await query.message.reply_text(result[0], reply_markup=get_back_menu())


# =======================
# معالجة الأخطاء
# =======================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update %s caused error %s", update, context.error)
    if update and update.effective_message:
        await update.effective_message.reply_text("😔 حدث خطأ. اكتب /start للبدء من جديد.", reply_markup=get_main_menu())


# =======================
# التشغيل
# =======================

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("saved", saved_command))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("run", run_command))
    app.add_handler(CommandHandler("interview", interview_command))
    app.add_handler(CommandHandler("plan", plan_command))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("🚀 البوت يعمل...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()