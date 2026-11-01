# V9 — original project uploaded as individual files

تم حفظ مشروع GoldStation V9 كملفات مفكوكة في جذر المستودع، مع نقل الأصول الثنائية بنص Base64 إلى `binary_assets/`.

**لا تحتاج إلى ZIP ولا إلى Upload files يدوياً.**

أعد قاعدة الشموع والأرشيف السابق بالآتي من جذر المستودع:

```bash
python3 scripts/restore_v9_binaries.py
```

للاختبار والتحقق من البصمات:

```bash
python3 scripts/restore_v9_binaries.py --verify-only
```
