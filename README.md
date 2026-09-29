# Lifebot 🤖 — AI Coach & Pomodoro

نظام إنتاجية شخصي: مؤقت بومودورو عائم + مهام + مدرب AI (Hermes) + مزامنة ثنائية الاتجاه مع Joplin.

> Personal productivity system: floating Pomodoro timer + tasks + AI coach + two-way Joplin sync.

---

## المميزات | Features

- ⏱️ **بومودورو احترافي**: مؤقت عائم فوق الشاشة (Always on Top)، فترات تركيز + بريك قصير/طويل، صوت تنبيه، إشعارات، عدّ الدورات (long break كل 4).
- 📋 **مهام كاملة**: إضافة/حذف/إتمام (double-click)، أولويات، عدّاد 🍅 تلقائي لكل مهمة، تخزين SQLite.
- 🧠 **Hermes AI Coach**: خطة صباحية + حل الأعذار + مراجعة يومية — بـ Gemini AI عند توفر المفتاح، ووضع offline عند غيابه.
- 🔄 **مزامنة Joplin ثنائية الاتجاه**:
  - إضافة مهمة من البرنامج → تظهر فورًا في نوت بوك `Projects/Lifebot/Tasks` ومعاها tags + due date (آخر اليوم) عشان تظهر في لوحات Kanban/All-Tasks.
  - مهمة من Joplin (New to-do جوه نفس النوت بوك) → تُسحب للبرنامج بزر **⬇ Pull** + سحب تلقائي عند التشغيل.
  - منع التكرار: الـ POST يُرسل مرة واحدة، والتحقق بالعنوان قبل أي إعادة.
  - تنظيف المكررات القديمة: `python -m cli.app dedupe [--apply]`.
- 📊 **تحليلات**: دقائق التركيز (7 أيام)، توزيع بالتصنيف، streak الأيام.
- 💻 **CLI كامل** بـ Typer + Rich.

## التشغيل | Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # ثم املأ المفاتيح
python run_lifebot.py
```

## الإعداد | Configuration

`.env` (انسخه من `.env.example`):

```env
GEMINI_API_KEY=...        # اختياري — بدونه يعمل المدرب offline
JOPLIN_TOKEN=...          # من Joplin Desktop: Settings → Web Clipper → Authorization token
JOPLIN_BASE_URL=http://127.0.0.1:41184
```

`config/config.yaml`:

```yaml
joplin:
  base_url: "http://127.0.0.1:41184"
  token: "YOUR_JOPLIN_TOKEN"   # الأفضلية لمتغير البيئة JOPLIN_TOKEN
  folder_name: "Projects/Lifebot/Tasks"  # يدعم المسارات المتداخلة، وينشئ الناقص
  tags: "task,lifebot"        # تاجز لوحات الـ Kanban
```

> ملاحظة: التكامل يحتاج **Joplin Desktop مفتوحًا** (الـ Clipper على `41184`) — سيرفر الدوكر وحده لا يكفي، وزرار Synchronise **غير مطلوب** للإضافة (يحدث لحظيًا).

## الاستخدام | Usage

### الواجهة (GUI)

| تبويب | الاستخدام |
|---|---|
| ⏱️ Pomodoro | اختر مهمة والمدة → أرسلها للعداد العائم وابدأ |
| 📋 Tasks | إضافة (Enter)، إتمام (double-click)، حذف، مسح المنجز، **⬆ Sync** للدفع، **⬇ Pull** للسحب |
| 🧠 Hermes | خطة صباحية / حل عذر / مراجعة يومية |
| 📊 Analytics | إحصائيات + 🔄 تحديث |

### سطر الأوامر (CLI)

```bash
python -m cli.app list                    # المهام المفتوحة
python -m cli.app add "مهمة" --category Ops --priority high --estimate 2
python -m cli.app done <id|title>         # إتمام
python -m cli.app rm <id|title>           # حذف
python -m cli.app stats --days 7          # إحصائيات
python -m cli.app plan | python -m cli.app review
python -m cli.app dedupe                  # تقرير المكرر في Joplin (dry-run)
python -m cli.app dedupe --apply          # حذف المكرر (الأحدث يُحفظ، الباقي للـ Trash)
```

## لوحة Joplin (Kanban)

اعمل نوتة داخل `Tasks` فيها:

````markdown
```kanban
filters:
  rootNotebookPath: Projects/Lifebot/Tasks
columns:
  - name: To Do
    backlog: true
  - name: In Progress
    tag: wip
  - name: Done
    completed: true
```
````

## استكشاف الأخطاء | Troubleshooting

| الرسالة | المعنى والحل |
|---|---|
| `Joplin busy — wait and retry` | Joplin مشغول (بيعمل Sync) — انتظر ثواني وأعد |
| `Desktop closed?` | افتح Joplin Desktop وفعّل Web Clipper على `41184` |
| `Wrong JOPLIN_TOKEN` | انسخ التوكن من جديد من إعدادات Web Clipper |
| اللوحة صفر رغم وجود المهام | تأكد أن اللوحة تقرأ نفس النوت بوك + دوس ⟳ أعلى اللوحة |
| `Pull` لا يجد مهام Joplin | لازم **New to-do** (مش note) **داخل** نوت بوك المهام |

## التطوير | Development

```bash
python -m pytest tests/ -q     # 16 اختبار
```

البنية:

```
core/      models.py storage.py(SQLite) coach.py(Gemini+offline) joplin.py(API)
cli/       app.py (Typer)
config/    config.yaml prompt.py
data/      lifebot.db (+ todos.json القديم للهجرة)
tests/     test_lifebot.py
run_lifebot.py  (واجهة PyQt6)
```
