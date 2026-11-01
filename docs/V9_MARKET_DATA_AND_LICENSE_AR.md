# LuxAlgo / Volume Profile / TradingView — شرح الدمج

## الفرق بين الأداة والاستراتيجية
**مؤشر LuxAlgo** يحدد الأحداث الهيكلية BOS/CHoCH وLiquidity وFVG وOB، ويضع مستويات عرض/طلب؛ لا يحدد أوامر/أهداف كاملة آلياً دون قواعد دخول. 
**PO3** تجمع (1) نطاق تراكم 12 شمعة، (2) سحب مؤقت خارج النطاق، (3) استرجاع داخل النطاق، (4) إغلاق فوق/تحت منتصفه ضمن ست شموع، (5) توافق H4 المكتمل، (6) دخول في الشمعة التالية + وقف وهدف. هو تعديل بحثي منفصل، ليس نسخة من LuxAlgo.
**Volume Profile** يظهر POC (أعلى وزن حجمي) وVAH/VAL (حدود منطقة 70% من الحجم). من دون حجم تداول لا يُحسب بشكل صحيح.

## مصادر حجم التداول
cTrader Open API في ProtoOATrendbar يوفر `volume` = **عدد التيكات** في الشمعة، وليس حجم العقود الفعلية ولا توزيع الحجم الحقيقي عند كل سعر. لقد تحققنا من حقله في البروتوكول الرسمي: https://github.com/spotware/openapi-proto-messages/blob/main/OpenApiModelMessages.proto
مكتبتنا `engine/volume_profile.py` توزع Tick Volume بالتناسب مع تقاطع كل شمعة مع صفوف الأسعار، لتقدير histogram. لا يجوز تسميته **Order Flow حقيقي، CVD، Delta، أو Volume at Price حقيقي**. للوصول إلى مستويات أفضل قد تحتاج بيانات ticks أو حجم عقود بورصة الذهب GC، وهي ليست مكافئة لـXAUUSD spot.
مكتبة TradingView توفر أدوات **Fixed Range/Session Volume Profile** الأصلية إذا كانت ضمن خطة الحساب. للمقارنة المرجعية البحثية: https://github.com/regardhodler/tradingview-volume-profile (MPL-2.0)، https://github.com/mervinj3546/volume-profile (تأكد من الرخصة قبل النسخ). لم ننسخ أياً من المصدرين؛ ملفنا برمجة مستقلة وتقديرية.

## حقوق LuxAlgo
المصدر الذي قدمه المستخدم مرخّص CC BY-NC-SA 4.0؛ عند نسخ أو توزيع مشتق منه يلزم نسبة للمؤلف، وعدم الاستخدام التجاري، والمشاركة بالمثل. نحن لم نرفق ذلك المصدر أو نشتقه حرفياً داخل V9. لا تستخدم نفس مصدر LuxAlgo في بوت تجاري قبل مراجعة الترخيص أو أخذ إذن من الحقوقي.

## TradingView — من الجوال أو الكمبيوتر
1. افتح https://www.tradingview.com/chart/ واضبط الرمز XAUUSD من مصدر بيانات محدد، والفريم **5m**، وعلى **شموع عادية** وليست Heikin Ashi.
2. أضف مؤشر LuxAlgo الأصلي من **Indicators → Smart Money Concepts [LuxAlgo]** إذا أردت عرضه؛ لا تحتاج نسخه إلى المشروع.
3. لعرض PO3: افتح **Pine Editor → Create new → Strategy**، امسح المثال، والصق محتوى `tradingview/GoldStation_PO3_Reference_Research.pine`، ثم **Save → Add to chart**. افتح **Strategy Tester** لفحص النتائج وتحكّم بالرسوم والسبريد في خصائص الاستراتيجية.
4. لعرض SMC المستقل وVolume Profile: أضف كل ملف `.pine` آخر على حدة كـ **Indicator** بنفس الخطوات. لا يمكن لصق ثلاث تعليمات `indicator/strategy` في سكربت واحد.
5. إذا لم يظهر Pine Editor في تطبيق الجوال، افتح الموقع من متصفح Chrome وفعّل **عرض سطح المكتب**، أو استخدم حاسوباً. قد تختلف بعض أدوات Pine Editor حسب الجهاز.
6. ملفات Pine **لم تُجرَّب داخل محرر TradingView الحقيقي** في هذه الجلسة؛ أي خطأ compiler سيحتاج تصحيحه في بيئة TradingView نفسها. لا تعتبر تنبيهات TradingView أو نتائج Broker Emulator دليلاً على تعبئة cTrader.
7. احذر من تفعيل Webhook يفتح صفقات مباشرةً من TradingView. الأفضل إعادة جلب السعر والشموع من cTrader على السيرفر والتحقق من المخاطر والتفويض قبل التنفيذ.

## استراتيجيات مع فلاتر SMC أو VP
من داخل V9 الافتراضي **الطبقتان حسابهما/تسجيلهما فقط**، لا تغيّران التصويت القديم لطبقات V8؛ هذا يحمي PO3 المرجعية. لتفعيلهما كبوابات إلزامية:
`python -m scripts.context_layers_cli enable smc`
`python -m scripts.context_layers_cli enable vp`
من دون `volume` حي صالح، تفعيل VP gate سيرفض فرص التداول (fail-closed). للإيقاف:
`python -m scripts.context_layers_cli disable vp`

## الاختبار الصحيح لتحسين PO3
لا نضيف فلتر فقط لأنه يبدو جميلاً على الرسم. افصل فترة تدريب عن فترة اختبار غير مستخدمة، واحتسب كل إشارة على **شمعة مغلقة**، ودخول تالي بعد تكاليف حقيقية، وقارن PO3 الأصلية بـPO3+SMC، ثم PO3+VP ثم الاثنتين معاً. احسب صفقات كل سنة، Average R، Profit Factor، التراجع، توزيع أكبر الرابحين، وحساسية السبريد، وقارن بدخول عشوائي. لا يمكن إصدار حكم ربحية على فلتر VP باستخدام CSV قديم بلا حجم.
