"""Bilingual UI strings for Rakez (English source → Arabic).

The English text is the key: everything the app builds stays readable and
`t("...")` simply returns the Arabic version when Arabic is active. Unknown
strings fall through unchanged, so a missing translation never breaks the UI.

Only the GUI imports Qt; the CLI can use :func:`t` without Qt installed.
"""
from __future__ import annotations

LANGUAGES = {"English": "en", "العربية": "ar"}
DEFAULT_LANGUAGE = "en"

_state = {"lang": DEFAULT_LANGUAGE}


def set_language(code: str) -> str:
    """Switch the active language ('en' or 'ar'). Returns the applied code."""
    _state["lang"] = code if code in ("en", "ar") else DEFAULT_LANGUAGE
    return _state["lang"]


def get_language() -> str:
    return _state["lang"]


def is_arabic() -> bool:
    return _state["lang"] == "ar"


def t(text):
    """Translate one UI string. Non-strings and unknown text pass through."""
    if not isinstance(text, str) or _state["lang"] != "ar":
        return text
    return AR.get(text, text)


def tf(template: str, **kwargs):
    """Translate a template that contains ``{placeholders}``, then format it."""
    text = t(template)
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text


def detect_language() -> str:
    """Best-effort first-run language: Arabic system locale → Arabic."""
    try:
        import locale
        loc = (locale.getlocale()[0] or "").lower()
        if loc.startswith("ar"):
            return "ar"
    except Exception:
        pass
    try:
        import os
        if (os.environ.get("LANG") or "").lower().startswith("ar"):
            return "ar"
    except Exception:
        pass
    return DEFAULT_LANGUAGE


def _translate_prop(widget, getter, setter, role: str) -> None:
    """Remember the English source once, then always render from it.

    Each role (window title, tooltip, text, placeholder) keeps its own memo so
    the same widget can carry several translated strings.
    """
    src_key = f"i18nSrc:{role}"
    last_key = f"i18nLast:{role}"
    try:
        src = widget.property(src_key)
        current = getter()
        if src is not None:
            # the app replaced the text itself (new task title, timer, ...):
            # forget the memo instead of overwriting the new value
            last = widget.property(last_key)
            if current not in (last, src):
                widget.setProperty(src_key, None)
                widget.setProperty(last_key, None)
                src = None
        if src is None:
            if not isinstance(current, str) or current not in AR:
                return
            widget.setProperty(src_key, current)
            src = current
        target = t(src)
        if current != target:
            setter(target)
        widget.setProperty(last_key, target)
    except Exception:
        pass


def translate_tree(root) -> None:
    """Translate every static label/button/tooltip under ``root``.

    Idempotent and reversible: the English original is cached on each widget,
    so switching back to English restores it. Combo boxes are skipped on
    purpose — their text keys map to stored values (theme, design, category).
    """
    if root is None:
        return
    try:
        from PyQt6.QtWidgets import (QAbstractButton, QGroupBox, QLabel,
                                     QLineEdit, QTabWidget, QTextEdit, QWidget)
    except Exception:
        return

    widgets = [root]
    try:
        widgets += root.findChildren(QWidget)
    except Exception:
        return

    for w in widgets:
        _translate_prop(w, w.windowTitle, w.setWindowTitle, "title")
        _translate_prop(w, w.toolTip, w.setToolTip, "tip")
        if isinstance(w, QLabel):
            _translate_prop(w, w.text, w.setText, "text")
        elif isinstance(w, QAbstractButton):
            _translate_prop(w, w.text, w.setText, "text")
        elif isinstance(w, (QLineEdit, QTextEdit)):
            _translate_prop(w, w.placeholderText, w.setPlaceholderText, "text")
        elif isinstance(w, QGroupBox):
            _translate_prop(w, w.title, w.setTitle, "text")
        if isinstance(w, QTabWidget):
            try:
                sources = getattr(w, "_i18n_tabs", None)
                if sources is None:
                    sources = [w.tabText(i) for i in range(w.count())]
                    w._i18n_tabs = sources
                for i, src in enumerate(sources):
                    if i < w.count():
                        target = t(src)
                        if w.tabText(i) != target:
                            w.setTabText(i, target)
            except Exception:
                pass



# ---------------------------------------------------------------------------
# Arabic dictionary (keys are the exact English strings used in the UI)
# ---------------------------------------------------------------------------
AR = {
    # ---- floating widget ----
    "Select a Task": "اختر مهمة",
    "Deep Work": "عمل عميق",
    "Drag to resize": "اسحب لتغيير الحجم",
    "Task title... (Enter to add)": "عنوان المهمة... (Enter للإضافة)",
    "Add": "إضافة",
    "Close": "إغلاق",
    "Click to switch task": "اضغط لتبديل المهمة",
    "Start/Pause": "تشغيل/إيقاف",
    "Open dashboard": "فتح اللوحة",
    "Quick add task": "إضافة سريعة",
    "Start short break": "بدء بريك قصير",
    "Reset timer": "إعادة ضبط المؤقت",
    "Quit Rakez completely": "إغلاق ركّز نهائيًا",
    "Mark current task as done": "إنهاء المهمة الحالية",
    "🎯 FOCUS": "🎯 تركيز",
    "☕ SHORT BREAK": "☕ بريك قصير",
    "🌴 LONG BREAK": "🌴 بريك طويل",
    "DONE!": "انتهى!",
    "{n_done}/{total} done": "{n_done}/{total} منجز",
    "no tasks yet": "لا مهام بعد",
    "PHASE: {cat}": "المرحلة: {cat}",
    "(no open tasks)": "(لا مهام مفتوحة)",
    "No task selected — pick one first.": "لم تختر مهمة — اختر واحدة أولًا.",
    "⚠ Could not complete '{name}'.": "⚠ تعذّر إنجاز '{name}'.",
    "✓ '{name}' completed!": "✓ تم إنجاز '{name}'!",
    "short": "قصير",
    "long": "طويل",
    "Yes": "نعم",
    "No": "لا",

    # ---- dashboard chrome ----
    "Rakez ركّز - AI Coach & Pomodoro": "ركّز - مدرب ذكي وبومودورو",
    "🤖 Rakez ركّز Productivity System": "🤖 ركّز — نظام الإنتاجية",
    "📌 Show/Hide Floating": "📌 إظهار/إخفاء الودجت",
    "🟢 Gemini AI": "🟢 Gemini متصل",
    "🟡 Offline coach (set GEMINI_API_KEY)": "🟡 مدرب محلي (أضف GEMINI_API_KEY)",
    "🟡 Offline coach": "🟡 مدرب محلي",
    "⏱️ Pomodoro": "⏱️ بومودورو",
    "📋 Tasks": "📋 المهام",
    "🧠 Hermes AI Coach": "🧠 مدرب Hermes",
    "📊 Analytics": "📊 التحليلات",
    "⚙️ Settings": "⚙️ الإعدادات",

    # ---- pomodoro tab ----
    "Select a Task for this Focus Session:": "اختر مهمة لجلسة التركيز:",
    "Focus (min):": "تركيز (دقيقة):",
    "Break (min):": "بريك (دقيقة):",
    "Cycles completed: 0 (long break every 4)":
        "الدورات المكتملة: 0 (بريك طويل كل 4)",
    "Cycles completed: {n} (long break every 4)":
        "الدورات المكتملة: {n} (بريك طويل كل 4)",
    "📅 Log finished focus to Google Calendar":
        "📅 تسجيل جلسات التركيز في Google Calendar",
    "Creates a calendar event when a focus session completes":
        "ينشئ حدثًا في التقويم عند انتهاء جلسة تركيز",
    "🚀 Send Task to Floating Widget & Start": "🚀 أرسل المهمة للودجت وابدأ",

    # ---- tasks tab ----
    "Show:": "عرض:",
    "completed": "المنجزة",
    "📁 New Project": "📁 مشروع جديد",
    "Create a project, then add tasks to it": "أنشئ مشروعًا ثم أضف المهام إليه",
    "🗑 Delete Project": "🗑 حذف مشروع",
    "Deletes the selected project header (tasks become unassigned)":
        "يحذف المشروع المحدد (تبقى مهامه غير مصنّفة)",
    "📁 Move to Project": "📁 نقل إلى مشروع",
    "Assign the selected task to a project": "نقل المهمة المحددة إلى مشروع",
    "New task title... (Enter to add)": "عنوان مهمة جديد... (Enter للإضافة)",
    "low": "منخفضة",
    "medium": "متوسطة",
    "high": "عالية",
    "➕ Add": "➕ إضافة",
    "✓ Toggle Done (double-click)": "✓ إنجاز/إلغاء (نقر مزدوج)",
    "🗑 Delete": "🗑 حذف",
    "🧹 Clear completed": "🧹 حذف المنجزة",
    "⬆ Sync all to Joplin All-Tasks": "⬆ مزامنة الكل إلى Joplin",
    "Push every open task to the Joplin notebook (skips existing)":
        "يرسل كل مهمة مفتوحة إلى دفتر Joplin (يتجاهل الموجود)",
    "⬇ Pull from Joplin": "⬇ سحب من Joplin",
    "Import todos created in Joplin into Rakez (skips existing)":
        "يستورد مهام Joplin إلى ركّز (يتجاهل الموجود)",
    "📤 Selected → Google Tasks": "📤 إرسال المحددة إلى Google Tasks",
    "Push the selected task to Google Tasks": "يرسل المهمة المحددة إلى Google Tasks",
    "📥 Google Tasks → Rakez": "📥 استيراد من Google Tasks",
    "Import open Google Tasks (skips existing)":
        "يستورد مهام Google المفتوحة (يتجاهل الموجود)",

    # ---- coach tab ----
    "🌅 Morning Plan": "🌅 خطة الصباح",
    "🛡️ Resolve Snag / Excuse": "🛡️ حل عائق/عذر",
    "📊 Daily Review": "📊 مراجعة اليوم",
    "Hermes coach output will appear here...": "سيظهر ردّ المدرب هنا...",
    "Hermes is thinking... ⏳": "Hermes يفكّر... ⏳",
    "Resolve Snag": "حل عائق",
    "What obstacle or excuse are you facing?": "ما العائق أو العذر الذي تواجهه؟",
    "🔄 Refresh": "🔄 تحديث",

    # ---- settings tab ----
    "🌐 Language:": "🌐 اللغة:",
    "English": "الإنجليزية",
    "🎨 Theme:": "🎨 المظهر:",
    "Light mode applies to the dashboard and the floating widget.":
        "الوضع الفاتح يُطبَّق على اللوحة والودجت العائم.",
    "🔳 Floating widget size:": "🔳 حجم الودجت العائم:",
    "Width:": "العرض:",
    "Height:": "الارتفاع:",
    "Apply size": "تطبيق الحجم",
    "🎨 Accent color:": "🎨 لون التمييز:",
    "🖌️ Widget design & background:": "🖌️ تصميم الودجت والخلفية:",
    "Design:": "التصميم:",
    "Background:": "الخلفية:",
    "🔆 Widget transparency:": "🔆 شفافية الودجت:",
    "Opacity:": "الشفافية:",
    "🔔 Notification sound:": "🔔 صوت التنبيه:",
    "🔊 Test": "🔊 تجربة",
    "Preview the selected sound": "سماع الصوت المحدد",
    "🔑 API keys (saved locally, applied instantly):":
        "🔑 مفاتيح API (تُحفظ محليًا وتُطبَّق فورًا):",
    "GEMINI_API_KEY (empty = offline coach)": "GEMINI_API_KEY (فارغ = مدرب محلي)",
    "JOPLIN_TOKEN (Joplin → Web Clipper)": "JOPLIN_TOKEN (من Joplin → Web Clipper)",
    "Base:": "العنوان:",
    "Folder:": "المجلد:",
    "Tags:": "الوسوم:",
    "📅 Google Calendar + Tasks (OAuth client from Google Cloud Console):":
        "📅 Google Calendar + Tasks (عميل OAuth من Google Cloud Console):",
    "Client ID:": "معرّف العميل:",
    "Secret:": "السر:",
    "🔓 Authorize": "🔓 تفويض",
    "Open browser once to grant access": "افتح المتصفح مرة واحدة لمنح الوصول",
    "🔌 Test connection": "🔌 اختبار الاتصال",
    "Real API check: Google Tasks list + Calendar events access":
        "فحص حقيقي: قراءة مهام Tasks وأحداث التقويم",
    "⬆️ Updates:": "⬆️ التحديثات:",
    "🔄 Check for updates": "🔄 التحقق من التحديثات",
    "Compare this version against the latest GitHub release":
        "مقارنة النسخة بأحدث إصدار على GitHub",
    "⬇️ Download & Install update": "⬇️ تنزيل وتثبيت التحديث",
    "Download the new installer and install it automatically":
        "ينزّل المثبّت الجديد ويثبّته تلقائيًا",
    "Current version: {v}": "النسخة الحالية: {v}",
    "💾 Save settings": "💾 حفظ الإعدادات",
    "✓ saved to settings.json": "✓ تم الحفظ في settings.json",
    "⚠ save failed": "⚠ فشل الحفظ",

    # ---- updates ----
    "⏳ Checking...": "⏳ جارٍ الفحص...",
    "Checking GitHub for updates...": "جارٍ التحقق من GitHub...",
    "Unknown error": "خطأ غير معروف",
    "⚠ Update check failed: {msg}": "⚠ فشل فحص التحديثات: {msg}",
    "🆕 New version available: {latest} (you have {cur})":
        "🆕 إصدار جديد: {latest} (لديك {cur})",
    "✓ Up to date — {cur} is the latest release": "✓ لديك أحدث إصدار — {cur}",
    "Updates": "التحديثات",
    "You are on the latest version ({cur}).": "أنت على أحدث إصدار ({cur}).",
    "new version": "إصدار جديد",
    "This release has no installer file attached.\n"
    "Ask the publisher to attach Rakez-Setup-*.exe to the GitHub release.":
        "هذا الإصدار لا يحتوي على ملف مثبّت.\n"
        "اطلب من الناشر إرفاق Rakez-Setup-*.exe في صفحة الإصدار.",
    "Install update": "تثبيت التحديث",
    "New version {latest} is ready — open Settings and press Download & Install.":
        "الإصدار {latest} جاهز — افتح الإعدادات واضغط تنزيل وتثبيت.",
    "New version {latest} is available, but the release has no installer attached.":
        "الإصدار {latest} متاح، لكن صفحة الإصدار لا تحتوي على ملف مثبّت.",
    "Download and install Rakez {latest}{detail}?\n\n"
    "The installer will run silently and Rakez will close to finish.\n"
    "Your tasks and settings are kept.":
        "تنزيل وتثبيت ركّز {latest}{detail}؟\n\n"
        "سيعمل المثبّت بصمت ويُغلق ركّز لإكمال التثبيت.\n"
        "مهامك وإعداداتك محفوظة.",
    "⏳ Downloading…": "⏳ جارٍ التنزيل...",
    "⏳ Downloading… {pct}%": "⏳ جارٍ التنزيل... {pct}%",
    "Downloading Rakez {latest}…": "جارٍ تنزيل ركّز {latest}...",
    "⚠ Download failed: {err}": "⚠ فشل التنزيل: {err}",
    "Update failed": "فشل التحديث",
    "Could not download the update:\n\n{err}": "تعذّر تنزيل التحديث:\n\n{err}",
    "✓ Downloaded — installing and restarting…": "✓ تم التنزيل — جارٍ التثبيت وإعادة التشغيل...",
    "⚠ Could not start the installer": "⚠ تعذّر تشغيل المثبّت",
    "Update": "تحديث",
    "The installer could not be started.\n\nYou can run it manually:\n{path}":
        "تعذّر تشغيل المثبّت.\n\nيمكنك تشغيله يدويًا:\n{path}",
    "Installing update": "تثبيت التحديث",
    "Rakez will close now and the installer will finish the update.\n"
    "Open Rakez again after a few seconds.":
        "سيُغلق ركّز الآن ويكمل المثبّت التحديث.\n"
        "افتح ركّز مرة أخرى بعد ثوانٍ.",
    "Rakez": "ركّز",

    # ---- tray ----
    "Show Dashboard": "إظهار اللوحة",
    "Quit": "خروج",
    "Rakez ركّز": "ركّز",

    # ---- projects / tasks dialogs ----
    "New Project": "مشروع جديد",
    "Project name:": "اسم المشروع:",
    "Delete Project": "حذف مشروع",
    "Select a project header row first (📁 row).": "اختر صف مشروع أولًا (صف 📁).",
    "Delete project '{name}'?\nIts tasks stay but become ungrouped.":
        "حذف مشروع '{name}'؟\nستبقى مهامه لكن غير مصنّفة.",
    "Move to Project": "نقل إلى مشروع",
    "Select a task row first (not a project header).":
        "اختر صف مهمة أولًا (وليس صف مشروع).",
    "Choose project (it stays selected after):": "اختر المشروع (يبقى محددًا بعدها):",
    "📁 (No project)": "📁 (بدون مشروع)",
    "📂 Ungrouped — {n} open": "📂 غير مصنّفة — {n} مفتوحة",
    "Warning": "تنبيه",
    "Please select a task first!": "اختر مهمة أولًا!",
    "Cleared": "تم الحذف",
    "Removed {n} completed tasks.": "تم حذف {n} مهمة منجزة.",

    # ---- joplin ----
    "⚠ Joplin not configured — set JOPLIN_TOKEN":
        "⚠ Joplin غير مُهيّأ — أضف JOPLIN_TOKEN",
    "Joplin is not configured.\nSet JOPLIN_TOKEN in your .env file.":
        "Joplin غير مُهيّأ.\nأضف JOPLIN_TOKEN في ملف .env.",
    "⏳ syncing to Joplin...": "⏳ جارٍ المزامنة مع Joplin...",
    "✓ {created} added, {updated} fixed, {skipped} ok":
        "✓ أُضيفت {created}، صُلحت {updated}، سليمة {skipped}",
    "Joplin Sync": "مزامنة Joplin",
    "Added {created} task(s), fixed {updated} (tags/due date).\n"
    "{skipped} already fine.\n"
    "Check the Joplin notebook + All-Tasks board.":
        "أُضيفت {created} مهمة، وصُلحت {updated} (الوسوم/الموعد).\n"
        "{skipped} كانت سليمة بالفعل.\n"
        "راجع دفتر Joplin ولوحة All-Tasks.",
    "Sync failed:\n{err}": "فشلت المزامنة:\n{err}",
    "✓ everything already in All-Tasks ({n})": "✓ كل شيء موجود في All-Tasks ({n})",
    "⏳ pulling from Joplin...": "⏳ جارٍ السحب من Joplin...",
    "✓ Joplin has {n} todos in '{folder}' — pulled {added} ({skipped} already here)":
        "✓ لدى Joplin {n} مهمة في '{folder}' — سُحبت {added} ({skipped} موجودة بالفعل)",
    "Joplin Pull": "سحب من Joplin",
    "Imported {n} task(s) from Joplin.": "تم استيراد {n} مهمة من Joplin.",
    "No to-dos found in Joplin notebook '{folder}'.\n"
    "Make sure the to-do is inside that notebook\n"
    "(not in another notebook) and press Synchronise in Joplin first.":
        "لا توجد مهام في دفتر Joplin '{folder}'.\n"
        "تأكد أن المهمة داخل هذا الدفتر\n"
        "(وليس دفترًا آخر) واضغط Synchronise في Joplin أولًا.",
    "⚠ Joplin pull: {err}": "⚠ سحب Joplin: {err}",
    "✓ in Joplin All-Tasks": "✓ في All-Tasks",
    "⚠ Joplin: {err}": "⚠ Joplin: {err}",

    # ---- google ----
    "Google": "Google",
    "Google Test": "اختبار Google",
    "Client ID and Client Secret are required.\n\n"
    "Google Cloud Console → APIs & Services → Credentials →\n"
    "Create OAuth client ID → Desktop app → copy both values here.":
        "معرّف العميل والسر مطلوبان.\n\n"
        "Google Cloud Console → APIs & Services → Credentials →\n"
        "Create OAuth client ID → Desktop app → انسخ القيمتين هنا.",
    "⏳ opening browser for Google authorization...":
        "⏳ فتح المتصفح للتفويض مع Google...",
    "✓ Google connected": "✓ تم ربط Google",
    "Connected! Tokens saved locally.": "تم الاتصال! حُفظت بيانات الدخول محليًا.",
    "⚠ Google: {err}": "⚠ Google: {err}",
    "Authorization failed:\n{err}": "فشل التفويض:\n{err}",
    "⏳ testing Google connection...": "⏳ اختبار اتصال Google...",
    "Connection OK\n\n{msg}": "الاتصال سليم\n\n{msg}",
    "{msg}\n\nAuthorize now?": "{msg}\n\nهل تريد التفويض الآن؟",
    "Connection failed:\n\n{msg}": "فشل الاتصال:\n\n{msg}",
    "✓ in Google Tasks": "✓ في Google Tasks",
    "✓ Google has {n} open — pulled {added}":
        "✓ لدى Google {n} مهمة مفتوحة — سُحبت {added}",

    # ---- sessions / analytics ----
    "Session '{task}' recorded ({min}m).": "تم تسجيل الجلسة '{task}' ({min} دقيقة).",
    "Logged to Google Calendar 📅": "سُجّلت في Google Calendar 📅",
    "🎉 Focus '{task}' logged! Long break started.":
        "🎉 سُجّلت جلسة التركيز '{task}'! بدأ البريك الطويل.",
    "🎉 Session '{task}' recorded! Start {min}-min break?":
        "🎉 سُجّلت الجلسة '{task}'! تبدأ بريك {min} دقيقة؟",
    "☕ Break finished! Ready for next focus?":
        "☕ انتهى البريك! جاهز للتركيز التالي؟",
    "Total sessions: {total} | Last 7d: {recent}":
        "إجمالي الجلسات: {total} | آخر 7 أيام: {recent}",
    "Focus minutes (7d): {minutes}": "دقائق التركيز (7 أيام): {minutes}",
    "Tasks: {done}/{total} done | Open: {open} | Streak: {streak}d":
        "المهام: {done}/{total} منجزة | مفتوحة: {open} | الاستمرار: {streak} يوم",
    "Minutes by category (7d):": "الدقائق حسب التصنيف (7 أيام):",
    "(no focus sessions yet)": "(لا جلسات تركيز بعد)",

    # ---- command line (python -m cli.app) ----
    "Rakez focus system": "نظام تركيز ركّز",
    "Title must not be empty": "العنوان مطلوب",
    "Estimate must be >= 1": "التقدير يجب أن يكون 1 أو أكثر",
    "Added:": "أُضيفت:",
    "Assigned:": "نُقلت:",
    "Rakez Projects": "مشاريع ركّز",
    "Rakez Tasks": "مهام ركّز",
    "ID": "المعرف",
    "Name": "الاسم",
    "Progress": "التقدم",
    "Tasks": "المهام",
    "Title": "العنوان",
    "Cat": "التصنيف",
    "Pri": "الأولوية",
    "Done": "المنجز",
    "Category": "التصنيف",
    "Min": "دقيقة",
    "Task not found": "المهمة غير موجودة",
    "Not found": "غير موجود",
    "Done x": "تم الإنجاز",
    "Deleted": "حُذفت",
    "Sessions: {total} (last {days}d: {recent})":
        "الجلسات: {total} (آخر {days} يوم: {recent})",
    "Focus minutes (last {days}d): {minutes}":
        "دقائق التركيز (آخر {days} يوم): {minutes}",
    "Tasks: {done}/{total} done | streak: {streak}d":
        "المهام: {done}/{total} منجزة | الاستمرار: {streak} يوم",
    "Minutes by category ({days}d)": "الدقائق حسب التصنيف ({days} يوم)",
    "Opening browser for Google authorization...":
        "جارٍ فتح المتصفح للتفويض مع Google...",
    "Authorization failed:": "فشل التفويض:",
    "Authorized.": "تم التفويض.",
    "Token saved to data/google_token.json":
        "حُفظت بيانات الدخول في data/google_token.json",
    "Joplin not configured (set JOPLIN_TOKEN)":
        "Joplin غير مُهيّأ (أضف JOPLIN_TOKEN)",
    "Duplicate groups: {groups} ({notes} notes)":
        "مجموعات مكررة: {groups} ({notes} ملاحظة)",
    "Dry run — nothing deleted. Re-run with --apply to clean.":
        "تجربة فقط — لم يُحذف شيء. أعد التشغيل مع --apply للتنظيف.",
    "Deleted {n} duplicates (see Joplin Trash).":
        "حُذفت {n} نسخة مكررة (انظر سلة Joplin).",
}
