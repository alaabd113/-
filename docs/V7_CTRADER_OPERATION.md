> **وثيقة قديمة للتاريخ (V7). للتشغيل الفعلي اتبع README_AR.md الإصدار V8.**

# خطوات ربط cTrader Demo وتنزيل الشموع بصورة صحيحة

## ما تحتاجه من حسابك

حساب cTrader Demo مؤكد، تطبيق Open API مصرح به، `clientId`, `clientSecret`, `accessToken`, `ctidTraderAccountId`, `symbolId` لذهب وسيطك. لا تشارك المفاتيح ضمن المحادثة ولا ترفعها للمستودع العام. ملفات الإعدادات تحتوي قيم مثال فقط.

## فتح التطبيق والمصادقة

راجع `docs/CTRADER_AR.md` لإنشاء تطبيق عبر `https://openapi.ctrader.com/` وتفويض OAuth، ثم ضع القيم في Environment Variables. `CTRADER_ACCOUNT_ID` ليس رقم رمز الذهب بل رقم الحساب الذي تعيده واجهة حسابات التوكن. تشغيل `python -m ctrader.demo_client --task account` و `--task symbols` يؤكد وجود الحساب ورمز XAUUSD، ومن ثم استخدم `symbolId` المعاد من الوسيط.

## تنزيل الفريمات

```bash
pip install -r requirements-ctrader.txt
python -m scripts.download_ctrader_history --symbol-id 123456 \
  --from-utc 2026-10-20T00:00:00Z --to-utc 2026-11-01T00:00:00Z \
  --periods M1,M5,M15,M30,H1,H4,D1 --out-dir data/ctrader_live
```

يستخدم السكربت نوافذ قصيرة وحد `count=500` لكل طلب، ويرفض أي إجابة ناقصة من API أو `has_more=true`. الملف على سبيل المثال `5min.csv` مع `5min.csv.meta.json`؛ المجمّع يرفض خلط `ctidTraderAccountId`, `symbolId`, `period`. السعر يُستخرج من `ProtoOATrendbar` بقسمة Low والـDelta على 100000، مع الحفاظ على دقة الوسيط. مصدر الحجم `tick volume` وليس حجم عقود بورصة.

## تشغيل كل القواعد المتاحة على شموع cTrader الفعلية (دون صفقات)

```bash
python -m scripts.live_shadow_csv --source-dir data/ctrader_live --asof-now
python -m scripts.paper_daemon --source-dir data/ctrader_live --poll-seconds 30
```

أوامر المراقبة **لا تسحب الشموع لوحدها**؛ يجب أن يُشغّل تنزيل الشموع دورياً (Cron/Service) حتى تصل شموع جديدة. يحتاج المحرك من كل فريم كمية كافية لتسخين EMA وATR. لا يستخدم تاريخ SQLite المجهول المنطقة الزمنية لقرار دخول حي. يُرفض أي ملف شموع من دون مصدر وهوية وتوقيت UTC واضح. لا يرسل التطبيق صفقات، حتى إذا أضاءت جميع التأكيدات.

## طبقات القرار

1. بيانات موثقة من cTrader Demo وملفات Source Meta
2. شموع مكتملة، UTC، بدون تكرار أو أسعار غير منطقية
3. مولّدات الاستراتيجيات الـ75 التي حالتها ON في سجل التشغيل
4. أدلة سياقية محسوبة فقط: هيكل، سيولة، اندفاع، اتجاه H4، جلسة، تأكيد شمعة
5. هندسة الدخول والوقف والهدف ونسبة R:R
6. أسعار Bid/Ask حديثة ومطابقة للرمز وسقف السبريد
7. قيود المخاطرة وحجم الصفقة وفق بيانات الوسيط وحساب USD
8. سجل أمر غير مكرر قبل الإرسال، وتسوية حالات عدم اليقين
9. إدارة المركز بعد تنفيذ وسيط مؤكد، وليس قبول طلب محلي فقط

المراحل 1–5 متاحة كمراقبة وورقي جزئي مع الاستراتيجيات. المراحل 6–9 مكتوبة كفحوصات ووحدات ربط ولكن **ليست نظام تداول آلي منشوراً**.

## من يتحكم بالاستراتيجيات؟

`python -m scripts.strategies_cli disable STRATEGY_ID` للتعطيل و`enable` للتفعيل. يمكن ربط الأوامر `/gold_strategies`, `/gold_on`, `/gold_off` بمسار بوت Telegram الحالي من `engine/admin_commands.py` مع `owner_id` الحقيقي الموثق؛ **لم يتم ربط البوت الحالي آلياً**.

## مراجع الواجهة الرسمية

- https://help.ctrader.com/open-api/symbol-data/
- https://help.ctrader.com/open-api/connection/
- https://help.ctrader.com/open-api/proxies-endpoints/
- https://help.ctrader.com/open-api/model-messages/
- https://github.com/spotware/OpenApiPy
