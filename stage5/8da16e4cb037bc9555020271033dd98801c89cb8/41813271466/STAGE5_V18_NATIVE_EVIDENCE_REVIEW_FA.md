# BANK2ODOO — بازبینی شواهد Stage 5 در Head دقیق Qt

**وضعیت:** نامزد پیاده‌سازی و تحویل شواهد؛ نه پذیرش UI توسط متخصص/Owner، نه مجوز Merge یا Release.

- **مخزن و PR فعال:** [Bank2Odoo Draft #31](https://github.com/rezahh107/Bank2Odoo/pull/31)
- **base main:** `ccec758c92b65469403533d946b69d3035c09779`
- **Head واقعی آزمون و تصویربرداری:** `8da16e4cb037bc9555020271033dd98801c89cb8`
- **شاخه:** `ux/stage5-v18-native-20261104`
- **شاهد Windows QPA:** [Run 41813271466](https://github.com/rezahh107/Bank2Odoo/actions/runs/41813271466)، Job `126517567094` = SUCCESS؛ ناشر مستقل Job `126518681262` = SUCCESS.
- **CI عمومی:** [Run 41813271476](https://github.com/rezahh107/Bank2Odoo/actions/runs/41813271476)، Job `126517570105` در زمان ثبت این گزارش هنوز `in_progress` است؛ نتیجهٔ احتمالی آن پیشاپیش PASS فرض نشده است.
- **Artifact اصلی:** `13312919314` (نام `bank2odoo-stage5-v18-native-original-windows`)، ۴۸۶ عضو، SHA-256 بستهٔ ZIP: `96324ab032e4267659281ea1848856e437303b2246b28e292af444cee91ef747`.
- **محیط:** Windows hosted Server 2025 / Qt QPA=windows / PySide6=Qt 6.11.2 / Python 3.13 / فونت آزمون Vazirmatn v33.003 / styles: Windows11 (Light)، Fusion (dark hint). Dark و 125/150٪ فقط Qt *simulation* هستند.

## پوشش واقعی

مجموعهٔ ۱۷۷ تست Python/Qt با یک Skip در Job اختصاصی همین Head PASS بود. ۳۳۶ حالت Qt بومی (۲ تم × ۲ عرض × ۲ ارتفاع × ۳ مقیاس × ۱۴ وضعیت)، ۴۸۳ تصویر اصلی که SHA آن‌ها مستقلاً با Manifest منطبق است، صفر شکست دسترسی داخلی؛ کنترل منفی عرض ناکافی در هر سه مقیاس `NEEDS_REVIEW` شد. سه فضای کاریِ میزبان: ۱۰۲۴×۷۲۰، ۸۱۹×۵۷۶ و ۶۸۳×۴۸۰ پیکسل منطقی. قاب کامل در عامل ۱٫۰ برای ۱۱۲/۱۱۲ حالت جا شد؛ در عامل‌های ۱٫۲۵/۱٫۵ با عرض منطقی کمتر از حداقل ۹۰۰، ۰/۱۱۲ بود. **دسترسی داخلی PASS، ولی جا شدن قاب روی میزبان کوچک FAIL/خارج از دامنهٔ اثبات‌شده است** و اثبات DPI فیزیکی دستگاه مقصد نیست.

[ماتریس واقعی G1 تا G14 و حدود ادعا](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/STAGE5_V18_G1_G14_RESULTS_v1.json) · [Manifest عامل ۱٫۰](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/manifest.json) · [۱٫۲۵](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_25/manifest.json) · [۱٫۵](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_5/manifest.json)

## نقاط مشاهدهٔ تصویری (همه PNG اصلی و بدون تغییر)

| حالت | تصویر | شاهد |
|---|---|---|
| شروع | [initial](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_initial_top.png) | انتخاب فایل برجسته؛ نوار پنج‌مرحله‌ای RTL |
| خطای شناسایی | [detect_error](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_detect_error_top.png) | بانک ناشناخته، بدون fallback ساختگی |
| رضایت مالی | [approval](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_approval_top.png) | SHA-bound و تأیید صریح |
| توقف درخواست‌شده | [cancel_requested](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_cancel_requested_top.png) | worker واقعی، نتیجهٔ قبلی منتشر نشد |
| خطای تبدیل | [convert_error](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_convert_error_top.png) | ERROR از NOT_PROVEN جدا |
| نتیجهٔ نااحرازشده | [not_proven](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_not_proven_top.png) | NOT_PROVEN و اقدام انتخاب پوشه |
| افشای جزئیات | [detail_open](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_detail_open_bottom.png) | کلید Space کنترل Qt را باز کرد |
| در حال ذخیره | [saving](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_saving_top.png) | نامزد هنوز ذخیره‌شده محسوب نشد |
| خطای ذخیره | [save_error](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_save_error_top.png) | retry ضمنی مسدود |
| ذخیره موفق | [saved](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_900x650_saved_top.png) | اقدام اصلی اکنون «انتخاب گزارش بعدی» است |
| PASS | [pass](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/light_940x650_pass_top.png) | سازگاری شواهد مانده، نه مجوز ورود Odoo |
| Dark شبیه‌سازی‌شده | [saved-dark](https://github.com/rezahh107/Bank2Odoo/blob/evidence/stage5-v18-native-20261104/stage5/8da16e4cb037bc9555020271033dd98801c89cb8/41813271466/scale_sim_1_0/simulated_dark_900x650_saved_top.png) | contrast و QStyle مؤثر برای مقایسه، نه OS Dark واقعی |

## نقد مستقل هفت‌گانهٔ Expert/heuristic — نه آزمون حسابدار

۱. **Squint / Blur:** در تصویر اولیه، منبع و اقدام انتخاب فایل بالاترین کنتراست عمل را دارند؛ در نتیجه، اقدام انتخاب پوشه؛ و پس از ذخیره، اقدام گزارش بعدی. تراکم متن فرم همچنان بالاتر از کارت‌های پیشنهادی v18 است.

۲. **Grayscale:** دکمهٔ اصلی در حالت‌های مهم درخشندگی متمایز دارد؛ نوار مرحلهٔ فعال کم‌رنگ‌تر است. سنجش استاندارد contrast برای تمام برچسب‌ها/وضعیت‌های Disabled و High Contrast OS انجام نشده.

۳. **Three-second expert orientation:** ترتیب خواندن از ستون راست (فایل/اطلاعات مالی) به ستون چپ (نتیجه/ذخیره) از ساختار قابل تشخیص است. **هیچ مطالعهٔ فهم حسابدار انجام نشده.**

۴. **Removal:** هشدار «نامزد بررسی، نه ورود Odoo» هم در بالای فرم و هم در متن نتیجه با کارکردهای متفاوت دیده می‌شود. به دلیل مرز مالی، حذف آن بدون نظر متخصص توصیه نمی‌شود؛ اما تکرار متن و قاب‌های نتیجه هنوز نیازمند قضاوت متخصص UX است.

۵. **Next Step:** پیاده‌سازی اولیهٔ Stage 5 پس از ذخیره، دکمهٔ «انتخاب گزارش بعدی» را ثانویه نشان می‌داد؛ اصلاح در `79c7154...` و بازآزمون `41813271466` آن را تنها اقدام accent کرد. «ذخیره شد» دیگر تأکید دوم نیست.

۶. **Count:** پنج علامت مرحله، چهار گروه اصلی Qt و یک اقدام اصلیِ وابسته به وضعیت؛ هیچ چارچوب موازی پردازش مالی یا دکمهٔ دومِ انتشار واقعی اضافه نشده است.

۷. **Longest Content:** مسیرهای بسیار بلند ساختگی در QLineEdit قابل انتخاب و کپی‌اند؛ متن در کنترل یک‌خطی بریده می‌شود اما محتوای کامل از دست نمی‌رود. در ۳۳۶ حالت تستی scroll افقی کلی صفر بود؛ این ادعای آزمون صفحه‌خوان یا نمایشگر واقعی نیست.

### اختلاف با مرجع v18 پیشنهادی

مرجع HTML دارای سطوح کارت‌مانندِ نرم‌تر، چیدمان جمع‌وجورتر اعداد نتیجه، برچسب‌های پیام با رنگ‌های معنایی و disclosure تصویریِ روشن‌تر است. نسخهٔ بومی از کنترل‌های Qt/QStyle واقعی و دسته‌بندی گروه‌ها استفاده می‌کند و pixel-perfect نیست. ساختار پنج مرحله، RTL دو ستون، مرز رضایت مالی، PASS/NOT_PROVEN و ذخیرهٔ مستقل هم‌جهت با قصد طراحی است؛ **رسیدن به سطح «مطلوب» در نبود داوری UI/UX و تصویب Owner همچنان NOT_PROVEN است**.

## مرزهای تصمیم و بازگشت

- مرجع `BANK2ODOO-UIUX-DESIGN-v18` همچنان `PROPOSED / NOT_OWNER_APPROVED` است؛ مقایسه تصویری مجوز تغییر هدف یا پذیرش نیست.
- حداقل عرض ۹۰۰ منطقی و ترجیح شروع ۹۴۰، اعداد نامزدند؛ اگر دستگاه واقعی فضای منطقی کمتر از ۹۰۰ دارد، دستگاه خارج از envelope فعلی است و تصمیم جداگانهٔ Owner دربارهٔ هدف/دامنه لازم است، نه fallback پنهانی تک‌ستونی.
- حسابداری واقعی، فایل خصوصی، import/reconcile Odoo، DPI فیزیکی/صفحه‌خوان و رضایت کاربر نهایی آزمایش نشدند.
- فایل‌های `GOAL_AUTHORITY`، finance core، parsers، report/save، schema و main تغییر نکردند. هشت فایل UI/test/CI روی شاخهٔ Draft تغییر یافته‌اند؛ بازگشت با کنار گذاشتن Draft PR ممکن است.
- **هیچ Merge، Release، Deploy، انتشار نسخه یا Stage 6/7 در این مأموریت انجام نشده است.**
