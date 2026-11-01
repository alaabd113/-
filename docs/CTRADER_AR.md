> **وثيقة قديمة للتاريخ (V7). للتشغيل الفعلي اتبع README_AR.md الإصدار V8.**

# دليل الربط الكامل مع cTrader Open API — سحب الشموع، الأسعار، والتحضير لتنفيذ ديمو

**الإصدار:** 2026-11-01 · **الوسيط:** أي وسيط حقيقي يدعم cTrader Open API، بما فيه وسيطك إن كان الحساب فعلاً ضمن cTrader. حساب FxPro منفصل عن امتلاك تطبيق cTrader: لا تفترض أن بيانات تسجيل FxPro تعني تلقائياً وجود cTID/حساب cTrader مفعل.

## 0. حدود هذه الحزمة

* عمل `research.run_screen` على الشموع المخزنة تم فعلياً، بدون شبكة.
* كود cTrader/OpenApiPy مُنشأ وفق الرسائل الرسمية، وفُحصت بنيته واختبرت تحويلاته وقواعد سلامته دون شبكة. **لم أقم بتجربة مصادقة أو سحب مباشر أو فتح صفقة حقيقية/ديمو** لأنه لا توجد بيانات اتصال من الوسيط في بيئة العمل. يجب اختبار التوافق الفعلي مع نسخة SDK والوسيط وصلاحيات الحساب قبل الاعتماد.
* وظيفة CLI `ctrader.demo_client` **للقراءة فقط** (accounts, symbols, bars, quotes, reconcile). يوجد تابع بناء/إرسال أمر ديمو محمي `send_ready_demo_order` للدمج البرمجي لاحقاً، **وليس متصلاً بمسار تشغيل تلقائي**. هذا مقصود حتى لا تتحول نتائج بحثية إلى أوامر بالخطأ.
* لا يوجد كود اتصال بخوادم Live على الإطلاق؛ اسم المضيف ثابت `demo.ctraderapi.com`.

## 1. ماذا تحتاج أنت تحديداً؟

1. حساب **Demo داخل cTrader** مرتبط بـ cTrader ID (cTID) — وليس MT5 منفصلاً.
2. تطبيق ضمن `https://openapi.ctrader.com/` ← Applications ← Create application، ثم Client ID وClient Secret وRedirect URI الموافق عليها. قد تتطلب الموافقة من Spotware حسب حالة التطبيق.
3. موافقة OAuth من صاحب الحساب: استخدم `scope=accounts` لقراءة الأسعار والبيانات، و`scope=trading` فقط إذا قررت لاحقاً السماح بأوامر ديمو. لا تُرسل التوكنات داخل الشات ولا تضعها في GitHub.
4. `CTRADER_ACCOUNT_ID` هو **ctidTraderAccountId** الذي يعيده `ProtoOAGetAccountListByAccessTokenRes`، وليس رقم حساب البنك، وليس Client ID.
5. `CTRADER_SYMBOL_ID` يجب استخراجه من `ProtoOASymbolsListRes` لكل حساب ووسيط؛ الاسم XAUUSD أو GOLD قد يختلف.

## 2. تثبيت المتطلبات

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
# .venv\\Scripts\\activate
pip install -r requirements-ctrader.txt
```

الاعتماد الرسمي من Spotware هو `pip install ctrader-open-api` ويستخدم Twisted/Protobuf.

## 3. الحصول على صلاحيات OAuth

حدد Redirect URI في لوحة التطبيق، مثلاً `https://yourdomain.example/ctrader/callback` بعد أن يكون لديك مسار استقبال HTTPS تملكه. لا تستخدم رابطاً وهمياً عند التشغيل الفعلي.

```bash
export CTRADER_CLIENT_ID='YOUR_CLIENT_ID'
python -m scripts.oauth_url --redirect-uri 'https://YOUR-REAL-REGISTERED-CALLBACK' --scope accounts
```

افتح الرابط الذي يولّده الأمر على متصفحك، وافق على الحساب، وسيعاد توجيهك إلى عنوان callback ومعه `code` صالح تقريباً دقيقة واحدة. استبدل هذا `code` بطلب HTTPS إلى:

`GET https://openapi.ctrader.com/apps/token?grant_type=authorization_code&code=...&redirect_uri=...&client_id=...&client_secret=...`

داخل كود المشروع يمكن استخدام `ctrader.credentials.exchange_code(...)` و`refresh_token(...)`؛ **هذه الدوال تعيد رموزاً حساسة: خزّنها في Secret Store ولا تطبعها**. مدة access token نحو 30 يوماً؛ refresh token يتجدد ويرافقه access token جديد عند التجديد.

## 4. ضبط الأسرار (كلها خارج GitHub)

```bash
export CTRADER_CLIENT_ID='...'
export CTRADER_CLIENT_SECRET='...'
export CTRADER_ACCESS_TOKEN='...'
export CTRADER_REFRESH_TOKEN='...'
export CTRADER_ACCOUNT_ID='...'
export CTRADER_SYMBOL_ID='...'
```

لا تضع هذه السطور الحقيقية في أي ملف قد ترفعه إلى GitHub. في السيرفر استخدم Environment Variables أو Secret Manager، مع صلاحيات وصول ضيقة.

## 5. التحقق أن الحساب Demo

الترتيب الرسمي على اتصال TCP/TLS بــ `demo.ctraderapi.com:5035`:

```text
ProtoOAApplicationAuthReq(ClientId, ClientSecret)
  ↓ ProtoOAApplicationAuthRes
ProtoOAGetAccountListByAccessTokenReq(AccessToken)
  ↓ ProtoOAGetAccountListByAccessTokenRes
  تحقق: المطلوب accountId موجود و isLive = false
  ↓
ProtoOAAccountAuthReq(ctidTraderAccountId, AccessToken)
  ↓ ProtoOAAccountAuthRes
ProtoOASymbolsListReq(accountId)
  ↓ ProtoOASymbolsListRes (اختيار XAUUSD/GOLD ورقم symbolId)
```

```bash
python -m ctrader.demo_client --task account
python -m ctrader.demo_client --task symbols
```

الخادم الحي يختلف عن الديمو ولا يمكن إتمام صلاحية حساب حي على خادم الديمو.

## 6. سحب شموع XAUUSD التاريخية

`ProtoOAGetTrendbarsReq` يحتوي:

- `ctidTraderAccountId`: رقم حساب الديمو
- `symbolId`: الرقم الذي وجدته ضمن قائمة رموز الوسيط
- `period`: أحد M1/M5/M15/M30/H1/H4/D1
- `fromTimestamp`, `toTimestamp`: **Unix milliseconds UTC** (وليس ثوانٍ)
- `count`: سقف عدد الشموع في الرد (استخدم طلبات قصيرة واحترم قيود الخادم على الفترات)

مثال سحب نافذة **محددة بالأوقات**:

```bash
python -m ctrader.demo_client \
  --task bars \
  --symbol-id "$CTRADER_SYMBOL_ID" \
  --period M5 --from-ms 1793404800000 --to-ms 1793491200000 \
  --count 500 --output data/ctrader_live_m5.csv
```

الأرقام هنا **مثال فترة**؛ احسب الميلي ثانية للفترة الفعلية التي تريدها. للاشتراك في البيانات الجديدة، اطلب التاريخ المفقود فقط، ثم استخدم SubscribeSpots + SubscribeLiveTrendbar أو دورات طلبات تاريخ قصيرة. كود الحزمة الحالي ينفذ **نافذة تاريخ واحدة لكل أمر CLI** وليس جامعاً مجدولاً دائماً؛ بناء الجدولة يحتاج وقت تشغيل خادم وربط حساب فعلي.

**ترميز الشمعة في بروتوكول cTrader:**

```python
low   = bar.low / 100_000
open  = (bar.low + bar.deltaOpen) / 100_000
high  = (bar.low + bar.deltaHigh) / 100_000
close = (bar.low + bar.deltaClose) / 100_000
timestamp = bar.utcTimestampInMinutes * 60  # Unix seconds
```

الكود موجود في `ctrader/protocol.py` مع اختبار آلي لهذه المعادلات. حجم الشمعة `volume` في cTrader يمثل **tick volume** غالباً، وليس حجم العقود الفعلي في سوق مركزي. لا تختبر CVD الحقيقي منه وحده.

الرسائل المناسبة للحظي: `ProtoOASubscribeSpotsReq` لآخر Bid/Ask؛ وللشموع المتجددة `ProtoOASubscribeLiveTrendbarReq` بعد تفعيل اشتراك السعر. الرسم اللحظي أو إغلاق الشمعة يتحقق من توقيتها/آخر تحديثها، ولا يعامل الشمعة غير المكتملة كشمعة مغلقة.

```bash
python -m ctrader.demo_client --task quotes --symbol-id "$CTRADER_SYMBOL_ID"
```

الحدود الرسمية: حوالي **5 طلبات تاريخية في الثانية** و**50 طلباً غير تاريخي في الثانية لكل اتصال**. لا تبنِ استعلام M1 لكل ثانية من دون Cache.

## 7. كيف تتشكل صفقة على الديمو؟

```text
Receive completed XAUUSD candles
  → validate timezone + OHLC + completeness + source
  → market regime H4/H1 (completed only)
  → strategy candidates (PO3 frozen, experiments in SHADOW)
  → liquidity / structure / momentum / optional session checks
  → cross-check spread / R:R / SL cap / quote freshness
  → sizing from USD account equity + broker min/step/max volume
  → create idempotency key in SQLite before any network send
  → verify demo account, symbolId, fresh Bid/Ask and full symbol metadata
  → market order with relativeStopLoss / relativeTakeProfit
  → wait for server execution acknowledgement
  → reconcile open positions on restart; NEVER resend uncertain order
```

في cTrader Order Market ترسل `ProtoOANewOrderReq` مع:

```text
ctidTraderAccountId = DEMO_ID
symbolId            = BROKER_XAUUSD_ID
orderType           = MARKET
tradeSide           = BUY or SELL
volume              = integer volume in 1/100 of underlying units
clientOrderId       = deterministic unique key
relativeStopLoss    = abs(entry - SL) × 100000
relativeTakeProfit  = abs(TP - entry) × 100000
```

**مهم جداً:** `volume = 1000` تعني **10 وحدات أساس**، وليست 1000 لوت. استخدم `ProtoOASymbolByIdReq` لقراءة `minVolume`, `maxVolume`, `stepVolume`, `lotSize`, `digits` الفعلية، وتأكد أن ضمانات الوقف مسموحة للرمز/الحساب. لا تستخدم قيمة ثابتة للوت أو للـ pip.

أولاً تتم الموافقة على الإشارة عبر `engine.pipeline.assess`، وبعدها فقط يمكن استدعاء تابع `ctrader.demo_client.send_ready_demo_order(...)`. سيبقى رفض الإرسال حتى تتوفر:

- حساب Demo مصادق وتأكيد أنه ليس Live؛
- Metadata حقيقة من الوسيط نفسه، وسعر Bid/Ask حديث؛
- `mode=DEMO` و`allow_demo_order=true` في الإعدادات، والمتغيرين `CTRADER_DEMO_CONFIRMED=YES` و`CTRADER_ALLOW_DEMO_ORDER=YES`؛
- إشارة مسموحة، SL/TP صالحان، حساب مخاطرة USD، حجم صفقة مطابق لحدود الوسيط؛
- عدم وجود مفتاح طلب مكرر أو طلب سابق حالته غير معروفة.

**الحزمة لا تفعّل هذه الشروط افتراضياً؛ ولم تُختبر عملية إرسال حقيقية، لذا لا تفعّل الإرسال قبل إجراء اختبار طرف-إلى-طرف مع وسيطك وتفاصيل العقد.**

## 8. المراقبة بعد فتح الصفقة

- `ProtoOAExecutionEvent` يؤكد التنفيذ؛ **إرسال الرسالة لا يعني قبولها**.
- `ProtoOAReconcileReq` يعيد المراكز والأوامر المفتوحة بعد إعادة التشغيل؛ سجّل `clientOrderId` ولا تكرر الطلب عند انقطاع الرد.
- بعد التنفيذ، راقب السعر والمخاطرة والوقف، وطبّق قواعد TP1/TP2/TP3 بتعديل وإغلاق أجزاء الكمية وفق الحد الأدنى لدى الوسيط. **إدارة الأهداف الجزئية لم تُربط بعد بمنفذ Open API في هذا الإصدار**، لذلك تظل خطة تنفيذية وليست ميزة مشغلة.
- قيّد المحرك بحد خسارة يومي ومركز واحد، وحالة الطوارئ STOP TRADING. لا تستخدم Martingale أو مضاعفة الخسارة.

## 9. بيئة التشغيل 24/7

الشات نفسه ليس سيرفراً دائماً، ولا تضمن Android الخلفية تشغيل اتصال TCP 24/7. تحتاج خادماً يدعم Python/Twisted وتشغيل دائم مع Restart وSecret Manager وHeartbeat كل 10 ثوانٍ وحفظ SQLite على قرص دائم. مجدول يراقب الفريمات المكتملة ولا يستعلم بلا توقف.

مقترح نظم مهام: M1 تحديث كل دقيقة، M5 عند إغلاق كل خمس دقائق، M15/H1/H4 عند الإغلاق، والمراقب يراجع مراكز الديمو بشكل منفصل عن محرك الإشارات، مع سجل audit لكل قرار (أسباب الرفض لا تقل أهمية عن الصفقات).

## مراجع رسمية

- https://help.ctrader.com/open-api/
- https://help.ctrader.com/open-api/account-authentication/
- https://help.ctrader.com/open-api/connection/
- https://help.ctrader.com/open-api/proxies-endpoints/
- https://help.ctrader.com/open-api/symbol-data/
- https://help.ctrader.com/open-api/messages/
- https://github.com/spotware/OpenApiPy
