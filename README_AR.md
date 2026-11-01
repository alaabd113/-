# GoldStation V8 — محرك الذهب الجاهز للإرسال إلى cTrader DEMO

**هذه النسخة ليست مراقبة ورقية.** مسار التشغيل `python -m scripts.run_demo` ينزّل شموع cTrader، يشغّل مولّدات الاستراتيجيات المفعّلة، يمرّر الإشارات عبر طبقات التأكيد والمخاطرة، ثم **يرسل طلب أمر حقيقي إلى حساب cTrader Demo** حين تجتاز الإشارة جميع البوابات. أوامر الديمو تُرسل مع وقف وهدف نسبيين إلى خادم الوسيط، وليس بعد محاكاة محلية.

**حدود التحقق:** نجحت اختبارات الوحدة والمحاكاة المحلية، لكن لا توجد مفاتيح حساب cTrader داخل هذه البيئة ولا أمكن تنزيل حزمة `ctrader-open-api` هنا؛ لم تُجرَّب جلسة OAuth حقيقية أو تعبئة أمر على حساب Demo فعلي. لا يمكن اعتبار التكامل مع الوسيط مضمونا قبل اختبار الحساب بعد الربط. لا توجد آلية تتيح التداول على حساب LIVE في هذا التنفيذ؛ عنوان SDK ثابت `demo.ctraderapi.com:5035` والحساب يرفض `isLive=true`.

## بداية التشغيل، على سيرفر فيه اتصال إنترنت

1. تثبيت **Python 3.12** وتشغيل المشروع في مجلد خاص. `pip install -r requirements-ctrader.txt` أو `docker compose up -d --build`.
2. أنشئ **cTrader Open API application** من بوابة Spotware الرسمية وأكمل قبول التطبيق وتفويض **trading** لحساب **Demo**. شرح التفويض: `docs/CTRADER_AR.md`.
3. انسخ `config/.env.example` إلى `.env` في جذر المشروع، وأدخل `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`, `CTRADER_ACCESS_TOKEN`, `CTRADER_REFRESH_TOKEN`, `CTRADER_ACCOUNT_ID`, `CTRADER_SYMBOL_ID`. ضع الصلاحيات `chmod 600 .env` ولا ترفع الملف إلى GitHub. **الـaccount ID والـsymbol ID معرفات وليسا أسراراً، ولكن مطلوبان لمعرفة الحساب والذهب الصحيحين.**
4. لإصدار التوكنات، يمكنك أولاً تشغيل `python -m scripts.oauth_url --scope trading --redirect-uri https://your-registered-redirect` ثم إكمال التفويض في متصفحك، وبعد ظهور `?code=` استخدم `python -m scripts.finish_oauth --redirect-url 'FULL_RETURNED_URL' --registered-redirect-uri 'EXACT_REGISTERED_URI'`. انتبه: رابط إعادة التوجيه يحتوي كوداً مؤقتاً؛ لا ترسله لأحد ولا تشاركه في سجل عام. التوكنات تحفظ بصلاحيات محلية مقيدة.
5. للتأكد من الحساب: `python -m scripts.status_demo` (قراءة فقط). لتشغيل المحرك: `python -m scripts.run_demo`. لتشغيل دورة واحدة: `python -m scripts.run_demo --once`.
6. التشغيل الدائم: `docker compose up -d --build` ثم `docker compose logs -f`. الحاوية تحتاج سيرفراً دائماً مفتوح الاتصال، وليست ChatGPT نفسها.

**إعدادات `CTRADER_DEMO_CONFIRMED=YES` و`CTRADER_ALLOW_DEMO_ORDER=YES` موجودة بالفعل في نموذج `.env`: هي موافقة صريحة على إرسال الأوامر إلى حساب DEMO وحده. لا تضع بيانات حساب حقيقي.**

## اختيار الاستراتيجيات

المشروع يحمل **75 إعداد استراتيجية** قابلة للتشغيل، بعضها نسخ لنفس الطريقة بفريم أو وقف مختلف. جميعها `enabled=true` و`allow_demo=true` افتراضياً تلبية لطلب المستخدم، بما في ذلك الاستراتيجيات ذات النتائج التاريخية السلبية: لم تُحذف. لكنها لا تستطيع إرسال صفقة من دون تخطي شروط درجة A وسقف المخاطرة والسبريد. **إتاحة استراتيجية على DEMO لا تعني أنها مثبتة الربحية.**

```bash
python -m scripts.strategies_cli list
python -m scripts.strategies_cli disable BOLL_RSI_FADE_M5
python -m scripts.strategies_cli enable BOLL_RSI_FADE_M5
```

تتوفر أوامر Telegram للمالك `/gold_strategies`, `/gold_off ID`, `/gold_on ID` من بوت **منفصل اختياري** عند وضع `GOLD_TELEGRAM_BOT_TOKEN` و`GOLD_TELEGRAM_OWNER_ID` في `.env`، وإضافة `GOLD_TELEGRAM_POLL=YES` على بوت **مخصص لا يملك webhook نشطاً**. تستخدم الأوامر Telegram polling ولا تتصل تلقائياً بالبوت المنشور الذي يعمل بـwebhook. إذا كان نفس البوت يعمل بـwebhook فلا تشغّل polling بنفس التوكن؛ بدلاً من ذلك أدمج `engine/admin_commands.py` في webhook الحالي. أرقام الربحية السابقة ليست احتمال نجاح معتمداً.

## الطبقات ومسار الأمر

1. **البيانات:** تنزيل OHLC من cTrader Open API لكل الفريمات وإلحاق `.meta.json` لهوية الحساب/الرمز والفريم؛ رفض أي مصدر مختلط أو توقيت غير UTC.
2. **إغلاق الشمعة:** رفض شمعة لم تنتهِ وفريمات ذات بيانات غير كافية. لا تُستخدم بيانات SQLite التاريخية غير الموثق توقيتها في قرار حي.
3. **مولّد الإشارات:** استدعاء جميع `enabled` من `strategies/catalog.py`؛ PO3 الأصلية باقية؛ كل استراتيجية تُشغّل على فريمها.
4. **طبقات التأكيد:** الاتجاه HTF، الهيكل، السيولة، الاندفاع، الجلسة والتأكيد السعري. يحتاج المجموع 75/100 على الأقل؛ هذا **ترجيح قواعد وليس احتمال ربح**.
5. **التضارب:** في وجود إشارات مؤهلة متعارضة شراء/بيع، لا يُرسل أمر. لدى الحساب مركز واحد كحد أقصى إجمالاً.
6. **المخاطرة:** سقف السبريد 0.60 في سعر الذهب، مخاطرة اسمية حتى 0.25% من الرصيد لكل صفقة، حد يومي 1.5% (يُحسب من نقطة بدء اليوم المسجلة)، حد الوقف حسب نوع الاستراتيجية (10 للسكالبينج وأوسع للسوينغ)، وR:R لا يقل عن 1.5. تقبل فقط حسابات USD الصالحة وديمو مرخصة؛ **العمولات والانزلاق المحتمل غير المدرج قد يرفعان الخسارة الفعلية عن الميزانية النظرية**.
7. **التحقق لدى الوسيط:** يقوم عامل SDK **بإعادة الاتصال والتحقق** من Demo، واكتمال صلاحية الحساب، والرمز، وBid/Ask الحديث، والوقف الأدنى، وعدم وجود مراكز أو أوامر معلقة. أي تغيير مفاجئ في السعر قد يمنع إرسال الإشارة.
8. **الإرسال المحمي:** أمر `MARKET_RANGE` بحد انزلاق 0.20 في السعر، مع `relativeStopLoss` و`relativeTakeProfit` من لحظة تعبئة الأمر، ومع `clientOrderId` فريد ومخزّن في SQLite **قبل** الإرسال. يمكن للوسيط رفض الطلب، وهو المرجع النهائي لصحة التنفيذ.
9. **حالات التنفيذ:** `ORDER_FILLED` يميز التنفيذ المؤكد، `ORDER_REJECTED` يميز الرفض؛ وفقد الرد أو التنفيذ الجزئي يترك السجل `SUBMIT_UNCERTAIN` ويجمّد فتح صفقات إضافية حتى تُسوّى الحالة. إدارة SL/TP عند الوسيط لا تعتمد على استمرار عملية Python. لا توجد بعد إدارة تلقائية متعددة الأهداف أو تأمين/تريلينغ مخصصة لكل استراتيجية.

## تدقيق التشغيل

```bash
python -m unittest discover -s tests -v
python -m scripts.check_configuration
python -m scripts.run_demo --once
```

الأمر الأخير يتطلب إعداد الحساب، ويمكنه **إرسال صفقة Demo فعلاً** إذا صادف إشارة مستوفية الشروط؛ لا تستخدمه للتجربة الآمنة قبل أن تكون جاهزاً لهذا السلوك. افحص الحساب أولاً بـ `scripts.status_demo`.

## قيود صريحة

- لا يمكن إثبات «جاهز 100%» أو «ما ناقصه إلا المفاتيح» دون تجربة SDK مع بيانات الوسيط وصلاحيات OAuth الفعلية؛ سيرفر دائم وإنترنت وتثبيت المكتبات مطلوبان أيضاً.
- الـ75 قاعدتها التاريخية ليست 75 أفضلية مثبتة؛ قد تبقى جميعها صامتة إذا لم تجتز التأكيدات، ويمكنك إطفاء أي واحدة.
- سعر الذهب وقت الأخبار والسبريد والعمولة والهامش قد يجعل تنفيذ الديمو مختلفاً عن الباك تست.
- نتيجة PO3 التاريخية +5.92R مرجع بحثي مجمّد، لا يوجد ادعاء بمطابقتها بعد تغيير محرك التنفيذ.
- لا توجد واجهة ويب إدارية مرفوعة، ولا نشر للبوت القديم على GitHub/Cloudflare؛ خدمة Telegram الاختيارية محلية.
- لا تحفظ `.env` أو سجلات عملاء البوت في مستودع GitHub عام.

المراجع: https://help.ctrader.com/open-api/ و https://help.ctrader.com/open-api/messages/ و https://github.com/spotware/OpenApiPy .

---

## تحديث V9 — LuxAlgo SMC + PO3 على TradingView + Volume Profile

**ابدأ هنا:** `docs/V9_WORKPLAN_AND_AUDIT_AR.md` (جدول المهام والاختبارات والأخطاء المكتشفة) ثم `docs/V9_MARKET_DATA_AND_LICENSE_AR.md` (المعاني ودليل TradingView والترخيص).

تم الحفاظ على ملفات V8 ومرجع PO3 بدون تعديل، وإضافة:
- `engine/smc_context.py`: SMC مستقل، causal، لا ينسخ LuxAlgo.
- `engine/volume_profile.py`: POC/VAH/VAL من cTrader tick volume عند توفره، بلا ادعاء حجم حقيقي عند السعر.
- `engine/context_integration.py`: بوابتا تأكيد قابلتان للتشغيل/الإطفاء من `config/context_layers.json`.
- `scripts/context_layers_cli.py`: `status`, `enable smc`, `enable vp`, `disable smc`, `disable vp`.
- `tradingview/GoldStation_PO3_Reference_Research.pine`: استراتيجية بحثية مستقلة على 5 دقائق؛ **ليست مطابقة بالكامل** لخوارزمية PO3 Python من حيث التنفيذ/الإغلاق.
- `tradingview/GoldStation_SMC_Context_Original.pine`: مؤشر بنية سوق مستقلة على الشموع المؤكدة.
- `tradingview/GoldStation_Tick_Volume_Profile_Approx.pine`: تقدير بروفايل فوليوم على TradingView عند وجود `volume`.
- `results/v9_smc_m5_snapshot.json`: إحصاء إشارات SMC على 7190 شمعة قديمة، وليس اختبار أرباح جديداً.

**تحكم الطبقات:**
```bash
python -m scripts.context_layers_cli status
python -m scripts.context_layers_cli enable smc
python -m scripts.context_layers_cli enable vp
python -m scripts.context_layers_cli disable vp
python -m unittest discover -s tests -q
```

**السياسة الافتراضية:** SMC وVolume Profile محسوبتان للتفسير والتسجيل، لكن بواباتهما غير إلزامية (`false`)، حتى لا تتغير نتائج PO3 المرجعية بلا تجربة منفصلة. إذا فُعّلت بوابة Volume Profile والبيانات بدون حجم موجب فعلي، يتم رفض الأوامر بدلاً من اختلاق الحجم. وظائف cTrader Demo القديمة لم تتغير في مسار الإرسال. يرجى اختبار ملفات Pine أولاً في محرر TradingView؛ لم يتوفر مترجم Pine أو حساب تداول مربوط ضمن بيئة المراجعة.
