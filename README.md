# 🎓 بوت علوم الحاسوب الذكي

بوت Telegram ذكي لطلاب علوم الحاسوب مع:

## الميزات
- 💻 شرح الكود
- 🔧 تصحيح الأخطاء
- ▶️ تنفيذ كود Python محدود
- 📝 كويز AI ذكي
- 🎯 محاكاة مقابلة تقنية
- 📋 خطة دراسية مخصصة
- 🃏 فلاش كاردز
- 💾 حفظ الإجابات
- 📈 إحصائيات المستخدم
- 🌐 دعم اللغة العربية

## المتطلبات
- Python 3.10+
- Telegram Bot Token (من @BotFather)
- Groq API Key (من https://console.groq.com)

## التثبيت محليًا

```bash
# 1. استنساخ المستودع
git clone https://github.com/esaambcem-lgtm/cs-bot.git
cd cs-bot

# 2. إنشاء بيئة افتراضية
python3 -m venv .venv
source .venv/bin/activate  # على Windows: .venv\Scripts\activate

# 3. تثبيت المكتبات
pip install -r requirements.txt

# 4. إنشاء ملف البيئة
cp .env.example .env

# 5. تعديل .env وإضافة المفاتيح
# TELEGRAM_TOKEN=your_token_here
# GROQ_API_KEY=your_api_key_here

# 6. تشغيل البوت
python bot.py
```

## النشر على Render

1. ارفع المشروع إلى GitHub
2. افتح https://render.com
3. أنشئ خدمة جديدة (New > Web Service)
4. اربط مستودعك
5. اختر `python` كـ environment
6. أضف متغيرات البيئة:
   - TELEGRAM_TOKEN
   - GROQ_API_KEY
7. اضغط Deploy

## النشر على Railway

1. ارفع المشروع إلى GitHub
2. افتح https://railway.app
3. أنشئ مشروع جديد
4. اربط مستودعك
5. أضف متغيرات البيئة
6. اضغط Deploy

## الأوامر

```
/start - البداية
/help - المساعدة
/quiz - كويز
/run - تنفيذ كود Python
/interview - محاكاة مقابلة
/plan - خطة دراسية
/stats - الإحصائيات
/saved - الإجابات المحفوظة
/clear - مسح السجل
```

## الهيكل

```
cs-bot/
├── bot.py              # الملف الرئيسي
├── requirements.txt    # المكتبات المطلوبة
├── .env.example        # مثال على متغيرات البيئة
├── .gitignore          # ملفات لتجاهلها
├── Procfile            # للنشر على Heroku
├── runtime.txt         # إصدار Python
├── render.yaml         # إعدادات Render
└── README.md           # هذا الملف
```

## الأمان

⚠️ **تحذير:**
- لا تضع التوكن أو المفتاح مباشرة في الكود
- استخدم ملف `.env` للتخزين الآمن
- لا ترفع `.env` إلى GitHub
- تنفيذ الكود محدود للحماية

## الترخيص

MIT License

## المساهمة

نرحب بالمساهمات! يرجى:
1. Fork المشروع
2. أنشئ فرع للميزة الجديدة
3. أرسل Pull Request

## الدعم

إذا واجهت مشاكل:
- تأكد من صحة TELEGRAM_TOKEN و GROQ_API_KEY
- تحقق من اتصالك بالإنترنت
- استخدم `/clear` لمسح السجل
- تحقق من السجلات للأخطاء

---

**تم الإنشاء بواسطة:** @esaambcem-lgtm
**التحديث الأخير:** 2026-06-23