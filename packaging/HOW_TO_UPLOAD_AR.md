# رفع أرشيف GoldStation V9

المستودع خاص. احفظ الملفات الأربعة `GoldStation_V9_PART_0X_of_04.zip` في مجلد `releases/v9/` عبر GitHub > Add file > Upload files، أو أرفقها كملفات في GitHub Release؛ فهي أقل من 10MB لكل ملف.

بعد التنزيل: فك الأربعة في مجلد واحد، وانسخ إليه `packaging/MANIFEST.json` و`packaging/REBUILD_V9.py`، وشغّل `python3 REBUILD_V9.py`. السكربت يراجع بصمات SHA256 ويعيد أرشيف V9 الأصلي.

**ملحوظة**: العناصر الثنائية لم تُرفع آلياً عبر الموصل؛ هذا الملف هو دليل رفع وليس إثبات وجود الملفات في GitHub.
