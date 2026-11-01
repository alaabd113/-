# GoldStation V9 — cTrader Demo & Trading Research

**النسخة الأصلية V9 محفوظة في هذا المستودع الخاص كملفات مفكوكة + أجزاء ثنائية قابلة للاستعادة.**

## المحتويات

- `engine/` — المحرك متعدد الطبقات، إدارة المخاطرة، SMC، Volume Profile
- `ctrader/` — اتصال cTrader Open API وإرسال أوامر Demo
- `strategies/` — 75 إعداد استراتيجية وسجل التفعيل والإيقاف
- `research/` — إعادة الاختبار وفحص المتانة
- `scripts/` — التشغيل، OAuth، إدارة الاستراتيجيات، استعادة البيانات
- `tradingview/` — PO3 وSMC وVolume Profile بصيغة Pine Script
- `data/ctrader/` — شموع cTrader التاريخية CSV على الفريمات السبعة
- `results/` — نتائج الباك تست
- `legacy/` — الشيفرات القديمة المنقولة من V9
- `binary_assets/` — قاعدة `candles.db`، وأرشيف المشروع السابق، محفوظان في أجزاء Base64 صغيرة مع بصمات SHA-256

## استعادة الملفات الثنائية (بعد Git clone)

يلزم Python 3.11 أو أحدث. في جذر المستودع:

```bash
python3 scripts/restore_v9_binaries.py
python3 scripts/restore_v9_binaries.py --verify-only
```

السكريبت يُنشئ:
- `data/candles.db` (16,363,520 بايت)
- `data/candles.db-shm` (32,768 بايت، ملف جانبي تاريخي)
- `data/candles.db-wal` (0 بايت)
- `legacy/GoldStation_Previous_Complete_Project_Quarantined.zip` (35,500,152 بايت)

**لا تفتح قاعدة SQLite مع نسخ WAL/SHM غير متوافقة عبر سيرفر حي.** عند الاستخدام، تحقق من القاعدة وأزل ملفات WAL/SHM التاريخية بعد التأكد من عدم وجود معاملات معلّقة؛ فهي محفوظة فقط لتطابق النسخة الأرشيفية.

## تشغيل اختبارات محلية

```bash
python3 -m pip install -r requirements-research.txt
python3 -m scripts.verify_all
```

**التداول غير مفعّل على حسابك حالياً.** يحتاج الربط بتطبيق cTrader Open API، مفاتيح `.env` خاصة، وحساب Demo واختبار اتصال الوسيط. لا ترفع الأسرار إلى GitHub.

## ترخيص

مؤشرات `tradingview/` من إعداد GoldStation كمشروعات بحثية. كود LuxAlgo الذي أرسله المستخدم مرخّص CC BY-NC-SA؛ لا نفترض أن نسخة المؤشر مستقلة أو مطابقة لكود LuxAlgo الأصلي. راجع تراخيص أي مكونات من أطراف ثالثة قبل التوزيع.

## سلامة النسخة

- `MANIFEST_SHA256.json`: بصمات ملفات مشروع V9 الأصلية
- `binary_assets/MANIFEST.json`: بصمات الأصول الثنائية وأجزائها
- `scripts/restore_v9_binaries.py`: إعادة التجميع والتحقق من كل قطعة

تم رفع ملفات المشروع ومحتويات الأرشيف الثنائي عبر حساب GitHub الموصول `alaabd113`. لا تحتاج إلى رفع ملفات ZIP الأربعة الأصلية.
