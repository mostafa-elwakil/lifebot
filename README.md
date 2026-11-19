<div align="center">

<img src="assets/logo.svg" width="88" alt="Rakez logo" />

# Rakez ركّز
**نظام إنتاجية شخصي كامل: بومودورو عائم + مهام ومشاريع + مدرب ذكي + مزامنة مع Joplin وGoogle.**

[![Release](https://img.shields.io/github/v/release/mostafa-elwakil/lifebot?label=latest&color=7aa2f7)](https://github.com/mostafa-elwakil/lifebot/releases/latest)
[![Build](https://github.com/mostafa-elwakil/lifebot/actions/workflows/build-windows.yml/badge.svg)](https://github.com/mostafa-elwakil/lifebot/actions/workflows/build-windows.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-9ece6a)](#-التنزيل)

**🌐 [العربية](README.md) · [English](README.en.md)**

[التنزيل](#-التنزيل) · [المميزات](#-المميزات) · [الموقع](#-الموقع) · [الأسئلة الشائعة](#-استكشاف-الأخطاء)

</div>

---

## ✨ المميزات | Features

### ⏱️ بومودورو عائم فوق كل البرامج
- مؤقت Always-on-Top بتصاميم متعددة: **Glass Pill / Neon Card / Split Flip / Typewriter**.
- فترات تركيز + بريك قصير/طويل تلقائي (كل 4 دورات)، أصوات تنبيه، إشعارات، ونسبة تقدم حية.
- تشغيل/إيقاف، إعادة ضبط، تبديل المهمة من داخل الودجت نفسه.

### 📁 مشاريع ومهام بنسبة إنجاز
- أنشئ **مشاريع** وضع فيها المهام، ويُحسب التقدم تلقائيًا: `2/5 (40%)`.
- تجميع المهام تحت عنوان كل مشروع + قسم للمهام غير المصنفة.
- نقل مهمة موجودة لمشروع، أو إنشاء مشروع جديد مباشرة من الحوار.
- حذف مشروع لا يحذف مهامه — تصبح غير مصنفة.

### 🧠 Hermes AI Coach
- خطة صباحية، حل الأعذار، ومراجعة يومية.
- يعمل مع **Gemini** عند إضافة المفتاح، وبدونه يقدّم وضع **Offline** مفيدًا بدون إنترنت.

### 🔄 مزامنة ثنائية الاتجاه
- **Joplin**: مهامك تظهر فورًا في `Projects/Lifebot/Tasks` مع tags وموعد استحقاق، وسحب مهام Joplin للبرنامج (زر Pull + تلقائي عند التشغيل). أمر `dedupe` لتنظيف التكرار.
- **Google Tasks**: دفع/سحب المهام.
- **Google Calendar**: تسجيل جلسات التركيز المنتهية كأحداث تلقائيًا.
- **زر Test connection** يتحقق فعليًا من الصلاحيات، ورسائل أخطاء ودّية (مثل `access_denied` مع خطوات الحل).

### 📊 تحليلات وتقدّم
- دقائق التركيز خلال 7 أيام، توزيع الدقائق حسب التصنيف، الأيام المتتالية (Streak)، المهام المنجزة.

### 🎨 مظهر فاتح وداكن
- ثيم **Dark (Tokyo Night)** و**Light (Paper)** للنافذة والودجت.
- تخصيص لون التمييز، حجم الودجت، شفافيته، وخلفيته (بما فيها خلفيات فاتحة).

### ⬆️ تحديثات بضغطة واحدة
- البرنامج يفحص GitHub Releases عند التشغيل، ثم زر **Download & Install update** ينزّل المثبّت ويعرض نسبة التقدم ويثبّت ويغلق البرنامج تلقائيًا — بدون فتح صفحة الإصدارات.

### 💻 CLI + Local API
- كل شيء متاح من الطرفية (إضافة/إتمام/إحصاءات/مشاريع/مزامنة).
- HTTP API محلي للمصادقة والتكامل مع أدوات خارجية.

### 🌐 واجهة عربية وإنجليزية
- بدّل اللغة من **Settings → 🌐 Language** — النافذة والودجت وكل الرسائل تتغير فورًا بدون إعادة تشغيل.
- الإنجليزية هي الافتراضية، ويمكن اختيار العربية يدويًا أو تلقائيًا حسب لغة النظام عند أول تشغيل.
- نفس الخيار في الطرفية: `python -m cli.app --lang ar projects`.

### ✈️ بوت تلجرام
- **تقارير جاهزة**: ما أُنجز اليوم + المهام المتبقية + نسبة كل مشروع + دقائق التركيز.
- **تقرير يومي تلقائي** في الساعة التي تختارها (افتراضيًا 8 مساءً).
- **إشعار فوري** عند إنجاز أي مهمة من البرنامج أو من الودجت العائم.
- **إدارة كاملة من الهاتف**: `/add عنوان` لإضافة مهمة، `/done 3` لإنهاء المهمة الثالثة، `/tasks` و`/projects` و`/report`.
- أي رسالة عادية للبوت تُضاف كمهمة جديدة — ويمكن إضافة المهمة داخل مشروع بـ `/add عنوان | مشروع`.
- يعمل البوت في خلفية البرنامج (Long polling) فلا يتجمد أو يتأخر أي شيء.

---

## 📥 التنزيل | Download

> **Windows 10/11** — لا يحتاج Python.

[**⬇️ تحميل أحدث نسخة (Rakez-Setup.exe)**](https://github.com/mostafa-elwakil/lifebot/releases/latest)

1. حمّل المثبّت وشغّله (اختر اختصار سطح المكتب إن أردت).
2. افتح Rakez — بياناتك تُحفظ في `%APPDATA%\Rakez\data`.
3. التحديثات القادمة بضغطة واحدة من: **Settings → Check for updates → Download & Install**.

> ملاحظة: الملف غير موقّع بشهادة Code Signing، فقد تظهر رسالة SmartScreen "Unknown publisher". اضغط **More info → Run anyway** — الناشر داخل خصائص الملف هو **Mostafa Elwakil**.
>
> Linux: `bash packaging/build_linux.sh` بعد تثبيت المتطلبات.

---

## 🌐 الموقع

الموقع التسويقي (GitHub Pages): **https://mostafa-elwakil.github.io/lifebot/** — ونسخته الإنجليزية: **/en/**

المصدر داخل مجلد [`website/`](website) — صفحة عربية RTL في الجذر وصفحة إنجليزية تحت `en/`، مع زر تبديل لغة، ثيم فاتح/داكن، وتحميل تلقائي لأحدث إصدار.

---

## 🚀 التشغيل من المصدر | Quickstart

```bash
git clone https://github.com/mostafa-elwakil/lifebot.git
cd lifebot
pip install -r requirements.txt
cp .env.example .env        # اختياري — املأ ما تحتاجه
python run_lifebot.py       # الواجهة الرسومية
```

جرّب من الطرفية:

```bash
python -m cli.app list
python -m cli.app add "تصميم الصفحة" --project Website --priority high
python -m cli.app projects
python -m cli.app stats --days 7
python -m cli.app google-test          # فحص ربط Google
python -m pytest tests -q              # 87 اختبارًا
```

---

## ⚙️ الإعداد | Configuration

### متغيرات `.env` (كلها اختيارية)

```env
GEMINI_API_KEY=            # مدرب Hermes أونلاين (بدونه وضع Offline)
JOPLIN_TOKEN=              # Joplin Desktop → Settings → Web Clipper
JOPLIN_BASE_URL=http://127.0.0.1:41184
GOOGLE_CLIENT_ID=          # من Google Cloud Console (Desktop app)
GOOGLE_CLIENT_SECRET=
API_TOKEN=                 # لحماية الـ HTTP API المحلي (Bearer)
TELEGRAM_BOT_TOKEN=        # توكن بوت من @BotFather (اختياري)
TELEGRAM_CHAT_ID=          # معرّف محادثتك في تلجرام (اختياري)
```

### `config/config.yaml`

```yaml
joplin:
  base_url: "http://127.0.0.1:41184"
  token: "YOUR_JOPLIN_TOKEN"
  folder_name: "Projects/Lifebot/Tasks"   # يدعم المسارات المتداخلة وينشئ الناقص
  tags: "task,lifebot"                    # تاجز لوحات Kanban
```

> Joplin يحتاج **Joplin Desktop مفتوحًا** (Web Clipper على المنفذ `41184`). زر Synchronise غير مطلوب للإضافة.

### ربط Google (Calendar + Tasks)

1. [Google Cloud Console](https://console.cloud.google.com) → مشروع جديد.
2. فعّل **Google Calendar API** و **Google Tasks API**.
3. **OAuth consent screen** → External → أضف بريدك في **Test users**.
4. **Credentials → Create OAuth client ID → Desktop app** → انسخ Client ID + Secret.
5. داخل Rakez → **Settings**: الصق القيمتين → **🔓 Authorize** → **🔌 Test connection**.

> ⚠️ إن ظهرت رسالة **"Access blocked: Rakez has not completed verification"** فمعناها أن حسابك ليس Test user. أضفه من OAuth consent screen → Test users. البرنامج يعرض لك هذه الخطوات تلقائيًا.
>
> في وضع Testing تنتهي صلاحية التوكن كل 7 أيام. للحل الدائم: **Publish app** → In production (تظل شاشة "unverified" طبيعية لتطبيق شخصي).

### ربط تلجرام (تقارير + إدارة مهام من الهاتف)

1. افتح [@BotFather](https://t.me/BotFather) في تلجرام → `/newbot` → انسخ **Token**.
2. في Rakez → **Settings → ✈️ Telegram**: الصق الـ Token.
3. أرسل `/start` للبوت من تلجرام، ثم اضغط **🔎 Detect chat ID** (أو أرسل `/id` وانسخ الرقم).
4. اضغط **🔌 Test** — ستصل رسالة تجريبية — ثم **📊 Send report now**.
5. اختياريًا: فعّل **Notify me when a task is completed** و**Daily report at 20:00**.

أوامر البوت: `/report` · `/tasks` · `/done N` · `/done id` · `/add عنوان | مشروع` · `/projects` · `/id` · `/help`.

---

## 🖥️ الاستخدام | Usage

### الواجهة الرسومية

| التبويب | الوظيفة |
|---|---|
| ⏱️ Pomodoro | اختر مهمة ومدة → أرسلها للودجت العائم وابدأ |
| 📋 Tasks | إضافة/إتمام/حذف، مشاريع ونسبة إنجاز، دفع وسحب Joplin وGoogle |
| 🧠 Hermes | خطة صباحية / حل عذر / مراجعة يومية |
| 📊 Analytics | إحصاءات التركيز والتصنيفات وStreak |
| ⚙️ Settings | الثيم، حجم/شفافية/تصميم الودجت، المفاتيح، Google، تلجرام، التحديثات |

اختصارات: `Enter` لإضافة مهمة، `double-click` لإتمامها.

### سطر الأوامر

```bash
python -m cli.app list                          # المهام المفتوحة
python -m cli.app add "مهمة" -p Website        # إضافة داخل مشروع (ينشئه إن لزم)
python -m cli.app projects                      # المشاريع وتقدمها
python -m cli.app assign "مهمة" "مشروع"        # نقل مهمة إلى مشروع
python -m cli.app done <id|title>
python -m cli.app rm <id|title>
python -m cli.app stats --days 7
python -m cli.app plan | python -m cli.app review
python -m cli.app dedupe [--apply]
python -m cli.app google-test [--authorize]
python -m cli.app telegram-test                # فحص التوكن + رسالة تجريبية
python -m cli.app telegram-chat-id             # اكتشاف معرّف المحادثة
python -m cli.app telegram-report [--no-send]  # التقرير (وإرساله إلى تلجرام)
python -m cli.app telegram-poll                # تشغيل البوت في الطرفية
python -m cli.app serve --port 8765
```

---

## 🔌 الـ HTTP API المحلي

```bash
python -m cli.app serve --port 8765
# API_TOKEN=secret python -m cli.app serve    # يتطلب Authorization: Bearer <token>
```

| الطلب | الوصف |
|---|---|
| `GET /health` | فحص الحالة |
| `GET /tasks` · `POST /tasks` | قائمة/إنشاء `{title, category?, priority?, estimate?, project_id?}` |
| `PUT /tasks/<id-or-title>` | تحديث `{completed?, title?, category?, priority?, project_id?}` |
| `DELETE /tasks/<id-or-title>` | حذف مهمة |
| `GET /projects` | المشاريع مع `total/done/pct` |
| `POST /projects` | إنشاء مشروع `{name}` |
| `DELETE /projects/<id-or-name>` | حذف مشروع (المهام تبقى غير مصنفة) |
| `GET /projects/<id>/tasks` | مهام مشروع (و`_NO_PROJECT_` لغير المصنفة) |
| `GET /sessions` · `POST /sessions` | جلسات التركيز |
| `GET /stats?days=7` | الإحصاءات |

---

## 🧪 التطوير والبناء

```bash
python -m pytest tests -q          # 87 اختبارًا

python packaging/build_windows.py  # dist/Rakez.exe
iscc packaging/Rakez.iss           # dist/Rakez-Setup-<version>.exe
```

- الإصدار الحالي يُحدَّد في: `core/updater.py` (`APP_VERSION`)، `packaging/Rakez.iss`، `packaging/version_info.txt`.
- **GitHub Actions** يبني ويختبر المثبّت على كل **tag** جديد (`v*`) وينشره تلقائيًا في Releases.
- صفحات الموقع تُنشر تلقائيًا من `website/` عبر GitHub Pages.

### هيكل المشروع

```
run_lifebot.py        الواجهة الرسومية (PyQt6) + الودجت العائم
core/
  models.py           نماذج المهمة
  storage.py          SQLite + المشاريع + الهجرة من JSON
  coach.py            Hermes (Gemini + Offline)
  joplin.py           عميل Joplin Web Clipper
  google_sync.py      Calendar + Tasks (OAuth2)
  telegram.py         بوت تلجرام (تقارير + أوامر)
  updater.py          فحص/تنزيل/تثبيت التحديثات
  api.py              HTTP API محلي
  settings.py         الإعدادات والثيمات
cli/app.py            أوامر Typer
config/               config.yaml + prompt.py
website/              الموقع التسويقي (GitHub Pages)
packaging/            PyInstaller + Inno Setup + Linux
tests/                87 اختبارًا
```

---

## 🩺 استكشاف الأخطاء

| الحالة | الحل |
|---|---|
| `Joplin busy — wait and retry` | Joplin يعمل Sync — انتظر ثوانٍ وأعد المحاولة |
| `Joplin not configured` | أضف `JOPLIN_TOKEN` أو الصقه في Settings |
| Pull لا يجد مهام | يجب أن تكون **New to-do** داخل نفس الـ notebook |
| `access_denied` من Google | أضف بريدك في Test users (الرسالة داخل البرنامج تشرح الخطوات) |
| `invalid_client` | أعد نسخ Client ID/Secret وتأكد أن النوع **Desktop app** |
| تحديث لا يظهر | تأكد من وجود اتصال، أو حمّل المثبّت يدويًا من Releases |
| اختفاء البيانات بعد تحديث | بياناتك في `%APPDATA%\Rakez\data` ولا تُمسح بالتحديث |

---

<div align="center">

صُنع بـ ❤️ بواسطة **Mostafa Elwakil**

⭐ لو أعجبك المشروع، اعمله Star على GitHub

</div>
