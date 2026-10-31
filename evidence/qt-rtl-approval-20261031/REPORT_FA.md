# گزارش مستقل احراز UI/UX — Bank2Odoo (صرفاً تشخیصی)

**وضعیت:** شواهد Windows CI تولید و منتشر شد؛ **اصلاح تولیدی انجام نشد**. پذیرش رایانهٔ فیزیکی حسابدار همچنان خارج از اثبات است.

## ۱. منشأ شواهد

- Production baseline: `5d4b950c29a73433c043a53dc266cee9192d3de4` (main، بدون تغییر).
- Diagnostic HEAD: `b9c4ec2c735831db3ff3801636010831af2a093e` در [Draft PR #12](https://github.com/rezahh107/Bank2Odoo/pull/12).
- Evidence publication: `3e5d0e6ea16d40fbc76e36958b740fa93eb9496e`، فقط در شاخهٔ مستقل `evidence/qt-rtl-checkbox-qualification-20261031`.
- [Windows rendered diagnostic run 41197206150](https://github.com/rezahh107/Bank2Odoo/actions/runs/41197206150): **success**؛ ۲۰ سناریو، ۷۶ PNG بومی.
- [Existing full verification run 41197206140](https://github.com/rezahh107/Bank2Odoo/actions/runs/41197206140): **success** در Head تشخیصی (بخش محصول با baseline تفاوتی ندارد).
- [measurements.json](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/measurements.json)، [SUMMARY.md](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/SUMMARY.md) و [EVIDENCE_MANIFEST.md](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/EVIDENCE_MANIFEST.md).

**محیط واقعی آزمایش:** Windows Server 2025 hosted runner (build 26100)، Python 3.13.12، PySide6/Qt 6.11.2، QPA=windows، Qt style: Light=windows11 و Dark=Fusion. فونت مؤثر Tahoma اندازهٔ 11.25pt؛ DPR=1. مسیر ColorScheme با hint آزمایشی برنامه عوض شد، نه با تشخیص حالت واقعی OS. تصاویر از `QWidget.grab()` با وضوح اصلی ثبت شدند.

## ۲. آزمایش A — ترتیب فضای کار

| فرضیه | نتیجه | شواهد اجرا |
| --- | --- | --- |
| نسخهٔ پایه در 940×830 ستون‌ها را معکوس می‌چیند | **CONFIRMED** | Light: ورودی x=18، نتیجه x=484؛ Dark: ورودی x=18، نتیجه x=472 |
| تغییر تنها جهت افقی از `QBoxLayout.RightToLeft` به `LeftToRight` ترتیب را درست می‌کند | **CONFIRMED** | Light: ورودی x=456، نتیجه x=18؛ Dark: ورودی x=466، نتیجه x=18 |
| در عرض‌های باریک، مسیر عمودی تقدم ورود اطلاعات بر نتیجه را حفظ می‌کند | **CONFIRMED** | 650 و 600: `TopToBottom`، ورودی y=161/159 و نتیجه y=796/792 |
| کنترل معکوس عمداً تشخیص داده می‌شود | **CONFIRMED** | baseline پهن `expected_order_present=false`، variant `true`، هر دو حالت Light/Dark |
| اسکرول افقی صفر است | **CONFIRMED در CI** | حداکثر horizontal scrollbar در تمام سناریوها صفر |
| ترتیب زنجیرهٔ Focus و نام دسترس‌پذیری بدون تغییر هستند | **PARTIALLY CONFIRMED** | زنجیرهٔ `nextInFocusChain` در دو حالت ثبت و بدون reorder گزارش شده؛ آزمون عملی با screen-reader انجام نشده |
| همهٔ کنترل‌ها با اسکرول و Tab برای کاربر قابل دسترسی‌اند | **NOT_PROVEN کامل** | اسکرول عمودی موجود و تبدیل/ذخیرهٔ ساختگی موفق است؛ تعامل دستی/assistive-tech در محیط مقصد انجام نشده |

**ابعاد واقعی:** درخواست 940×830 در Windows runner به پنجرهٔ **940×749** محدود شد (viewport در Light=928×749، Dark=926×749). اندازه‌های 650×520 و 600×480 دقیقاً ثبت شدند؛ عرض viewport در Light به‌ترتیب 638 و 588، در Dark برابر 636 و 586. DPR هر سه 1. بنابراین تصاویر 940×830 را به‌غلط تمام‌قد 830 معرفی نکنید.

**نمونه PNG اصلی قابل بازکردن در GitHub:**
- [Light 940 — baseline](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/rtl_baseline_light_940x830_initial.png) / [Light 940 — horizontal variant](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/rtl_horizontal_ltr_light_940x830_initial.png)
- [Dark 940 — baseline](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/rtl_baseline_dark_940x830_initial.png) / [Dark 940 — horizontal variant](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/rtl_horizontal_ltr_dark_940x830_initial.png)
- [Light 650 — initial](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/rtl_baseline_light_650x520_initial.png) / [Dark 600 — initial](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/rtl_baseline_dark_600x480_initial.png)
- [Light 940 — conversion result](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/rtl_horizontal_ltr_light_940x830_result.png) / [Dark 940 — saved](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/rtl_horizontal_ltr_dark_940x830_saved.png)

**کمترین اصلاح پیشنهادشده (اجرا نشده):** فقط در `bank2odoo/ui/window.py` مقدار جهت افقی `_workspace`، در مقداردهی اولیه و شاخهٔ پهن `_reflow_workspace()`، به `QBoxLayout.Direction.LeftToRight` تغییر کند. مسیر باریک `TopToBottom` و ترتیب افزودن ویجت‌ها دست‌نخورده بماند. Regression باید مختصات واقعی، نبود اسکرول افقی، فوکوس و دسترس‌پذیری را در هر دو تم و سه اندازه مقایسه کند.

## ۳. آزمایش B — نشانگر تأیید مالی در Dark

| فرضیه | نتیجه | شواهد |
| --- | --- | --- |
| QSS موجود روی ویجت محصول اعمال نمی‌شود | **REJECTED در محیط CI** | ۸۴ پیکسل border نشانگر در رنگ دقیق `#DCE7F0` دیده شد؛ QSS مؤثر نیز خوانده شد |
| ProxyStyle مانع کامل اعمال scoped border است | **REJECTED برای این مسیر** | همزمان `PM_IndicatorWidth/Height=22`، مستطیل 22×22، و رنگ QSS در رندر مشاهده شد |
| نشانگر unchecked در Dark همین CI واقعاً low contrast است | **REJECTED در CI؛ مشکل گزارش‌شدهٔ کاربر NOT_PROVEN** | border `#DCE7F0` در برابر سطح مجاور `#151A21`؛ نسبت پیکسلی **13.925:1** |
| تغییر تنها رنگ border در treatment اثر واقعی دارد | **CONFIRMED** | رنگ `#FF00FF` در ۸۴ نمونه و نسبت **5.573:1** مشاهده شد |
| کنترل منفی deliberately low contrast شناسایی می‌شود | **CONFIRMED** | border `#161B22` در مقابل `#151A21`، نسبت **1.010:1**، سهم نمونه‌های با نسبت ≥۳ صفر |
| حداقل 22px نشانگر و ارتفاع 52px ردیف پابرجاست | **CONFIRMED** | تمامی سناریوهای محصول اندازهٔ 22×22 و ارتفاع 52 را گزارش کردند |
| Space، کلیک در فضای خالی ردیف و لغو تأیید پس از تغییر زمینه فعال‌اند | **CONFIRMED در آزمون ساختگی** | همهٔ `space_checks`، `space_unchecks`، `full_row_click`، `context_edit_revokes` برابر true |
| حفظ ارتباط تأیید با SHA همان فایل در مسیر تبدیل و ذخیره | **CONFIRMED برای fixture ساختگی** | بعد از تأیید، digest برابر source digest و تبدیل/ذخیره موفق؛ پس از تغییر زمینه، تأیید لغو شد |
| فوکوس کیبورد و دسترس‌پذیری انسان در Windows 11 | **PARTIALLY CONFIRMED / NOT_PROVEN** | PNG فوکوس و نام دسترس‌پذیری موجود، اما نه پذیرش بصری واقعی و نه screen-reader بررسی نشده |
| منشأ نمونهٔ کم‌کنتراست گزارش‌شده در دستگاه مقصد | **NOT_PROVEN** | تفاوت physical OS/Theme/Build/DPI هنوز از راه CI تفکیک نشده است |

**روش اندازه‌گیری:** پنجرهٔ واقعی `QWidget.grab()` به‌صورت composited در DPR=1 گرفته شد. نشانگر با `QStyle.SubElement.SE_CheckBoxIndicator` تعیین شد؛ پس‌زمینه از ۱۲ نقطهٔ نزدیک، ۵/۷ پیکسل منطقی بالا/پایین نشانگر و x مرکز ±۳ نمونه‌برداری و رنگ غالب انتخاب شد. نمونه‌های border در فاصلهٔ ۱/۲ پیکسل منطقی داخل چهار لبه ثبت شد. نسبت‌ها با luminance خطی‌شدهٔ sRGB محاسبه شدند. این اندازه‌گیری pixel contrast محلی است؛ ادعای کیفیت ادراکی فونت یا WCAG برای کل کنترل نیست.

**PNGهای واقعی:**
- [Dark — unchecked اصلی](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/checkbox_baseline_dark_940x830_initial.png)
- [Dark — checked](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/checkbox_baseline_dark_940x830_checked.png)
- [Dark — keyboard focus](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/checkbox_baseline_dark_940x830_focus.png)
- [Dark — contrast negative](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/checkbox_negative_dark_940x830_initial.png)
- [Dark — bright-border diagnostic](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/checkbox_bright_border_dark_940x830_initial.png)
- [Light — بدون QSS تاریک](https://github.com/rezahh107/Bank2Odoo/blob/evidence/qt-rtl-checkbox-qualification-20261031/evidence/qt-rtl-approval-20261031/checkbox_baseline_light_940x830_initial.png)

**پیشنهاد کم‌ریسک B:** فعلاً تغییر CSS، حذف ProxyStyle یا طراحی مجدد در محصول توصیه نمی‌شود. ابتدا همان commit و نسخهٔ محصول در Windows 11 واقعی، سبک مؤثر، ColorScheme واقعی OS، فونت و DPI را در 100/125/150% ثبت و همراه screenshot اصلیِ مسئله مقایسه کنید. اگر low contrast در همان ساخت و شرایط تکرار شد، فقط مرز paint همان indicator را به‌صورت محدود و با control case حاضر اصلاح کنید.

## ۴. صحت، محدودیت‌ها و شکست‌های قبلی

- دو اجرای مقدماتی runner در سطح **diagnostic harness** با خطای native (یک بار هنگام آزمایش حذف درجاى proxy، و یک بار در garbage collection پایان فرایند پس از تولید تصاویر) متوقف شدند. این‌ها PASS نیستند و دربارهٔ منشأ مشکل UI اثبات مستقلی نمی‌دهند؛ variant حذف پرخطر کنار گذاشته شد و آزمون‌های مستقل هرکدام در یک Python process دارای QApplication مختص خود اجرا شدند.
- اجرای میانی `41196980370` با CI سبز بود اما مقایسهٔ QSS قابل استناد نبود: product refresh مقدار treatment را بازمی‌گرداند و نمونهٔ پس‌زمینه از checkbox grab شفاف بود. **فقط اجرای اصلاح‌شدهٔ `41197206150` مرجع نهایی B است.**
- Windows Server 2025 GitHub CI ≠ workstation Windows 11؛ ColorScheme override ≠ واقعی؛ DPR=1 ≠ پوشش scaling 125/150؛ موفقیت fixture ساختگی ≠ رفتار واقعی بانک و Odoo؛ screenshot ≠ درک حسابدار یا خوانایی با کمک فناوری‌های دسترس‌پذیری.
- هیچ کد موجود زیر `bank2odoo/` تغییر نکرد، هیچ فایل خصوصی/بانکی در evidence ثبت نشد، هیچ merge/release/deploy انجام نشد.

**وضعیت تصمیم:** اصلاح حداقلی جهت افقی برای مرحلهٔ پیاده‌سازی بعدی **پشتیبانی‌شده** است. اصلاح Dark approval تا وقتی علت نمونهٔ واقعی بازتولید و اندازه‌گیری نشود **تأیید نمی‌شود**.
