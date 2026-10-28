"""Persian, review-only accountant interface over the independent financial engine.

No bank parsing, monetary decisions or CSV serialization live in this module.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from threading import Event
import sys

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QProxyStyle, QStyle, QStyleFactory, QVBoxLayout, QWidget,
)

from bank2odoo.banks.reader import read_statement
from bank2odoo.core.engine import Context, Conversion, convert
from bank2odoo.reporting.output import save_candidate
from bank2odoo.validation.financial import StatementError, exact_sum


BANK_LABELS = {"melli": "بانک ملی — XLS قدیمی", "mellat": "بانک ملت — CSV"}
def preferred_style_key(styles: list[str], *, windows: bool) -> str | None:
    """Use Fluent widgets only when the installed Qt platform plugin exposes them."""
    if not windows:
        return None  # Preserve the system default on other platforms.
    available = {name.casefold(): name for name in styles}
    return available.get("windows11") or available.get("fusion")


def configure_application(app: QApplication) -> None:
    """Native controls first; do not mask them with a global widget stylesheet."""
    key = preferred_style_key(QStyleFactory.keys(), windows=sys.platform == "win32")
    if key is not None:
        style = QStyleFactory.create(key)
        if style is not None:
            app.setStyle(style)
    families = {family.casefold(): family for family in QFontDatabase.families()}
    # Reuse an installed Persian typeface. Bundling is unnecessary without
    # evidence of a missing family and a vetted redistributable font artifact.
    family = (families.get("vazirmatn") or families.get("tahoma")
              or app.font().family())
    app.setFont(QFont(family, 11))
    resolved = QFontInfo(app.font()).family()
    print(f"Bank2Odoo Qt style: {app.style().objectName()}; "
          f"font: {resolved}; available styles: {', '.join(QStyleFactory.keys())}")


def latin(text: object) -> str:
    """Isolate LTR amounts and filenames inside RTL explanatory text."""
    return "\u2066" + str(text) + "\u2069"


GENERAL_REVIEW = (
    "این فایل فقط نامزد بررسی است؛ پیش از ورود جداگانه در Odoo، بانک، "
    "واحد پول، ژورنال، دوره، مانده‌ها و تراکنش‌های قبلی را بررسی کنید."
)


def human_error(detail: str, *, saving: bool = False) -> str:
    """Human wording, not a claim about an unverified underlying cause."""
    message = detail.lower()
    if "already exist" in message or "output appeared" in message:
        return "فایل خروجی هم‌نام از قبل وجود دارد. پوشه‌ای دیگر انتخاب کنید یا فایل‌های قبلی را بررسی کنید."
    if "outside the public source checkout" in message:
        return "پوشه خروجی داخل پوشه کد برنامه است. یک پوشه خصوصی بیرون از آن انتخاب کنید."
    if "same existing private directory" in message:
        return "برای هر دو خروجی باید یک پوشه خصوصیِ موجود انتخاب شود."
    if saving:
        return "ذخیره هر دو فایل کامل نشد. مسیر، دسترسی و فضای دیسک را بررسی کنید؛ هیچ موفقیتی تأیید نشده است."
    if "balance mismatch" in message or "closing minus" in message:
        return "مانده‌های گزارش با گردش‌ها تطابق ندارند؛ خروجی ساخته نشد. گزارش بانک را بررسی کنید."
    if "jalali date" in message or "transaction time" in message:
        return "تاریخ یا ساعت یکی از ردیف‌های بانک معتبر یا قابل تشخیص نیست."
    if "amount" in message or "numeric" in message or "decimal" in message:
        return "مبلغ یا دقت اعشاری یکی از ردیف‌ها قابل تأیید نیست؛ هیچ مبلغی گرد نشده است."
    if "headers" in message or "header" in message or "xls" in message or "csv" in message:
        return "ساختار یا قالب فایل پشتیبانی نمی‌شود یا خواندن آن ممکن نیست."
    if "source/target unit" in message or "factor" in message or "journal" in message:
        return "اطلاعات مالی یا ضریب تأییدشده ناقص یا ناسازگار است."
    return "خواندن یا تبدیل فایل کامل نشد. جزئیات فنی را بررسی کنید."


def issue_label(issue: str) -> str:
    if "duplicate" in issue.lower():
        return "گردش احتمالاً تکراری یافت شد، اما حذف نشده است."
    if "shared-reference" in issue.lower() or "shared-ref" in issue.lower():
        return "چند گردش مرجع مشترک دارند؛ ارتباطشان تأیید نشده است."
    if "balance" in issue.lower() or "order" in issue.lower():
        return "شواهد موجود برای اثبات کامل ترتیب یا مانده کافی نیست."
    return "موردی برای بررسی حسابدار در گزارش کنترل ثبت شده است."


class _ApprovalIndicatorStyle(QProxyStyle):
    """Enlarge only the native checkbox metric; keep platform painting and focus."""

    def pixelMetric(self, metric, option=None, widget=None):
        native = super().pixelMetric(metric, option, widget)
        if metric in (QStyle.PixelMetric.PM_IndicatorWidth,
                      QStyle.PixelMetric.PM_IndicatorHeight):
            return max(native, 22)
        return native


class _FullRowCheckBox(QCheckBox):
    """Make the entire approved row a mouse target, not only its label glyphs."""

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)


class _Job(QObject):
    """One filesystem/engine operation; only the GUI thread publishes its outcome."""

    finished = Signal()

    def __init__(self, kind: str, state: dict, *, path: Path | None = None,
                 context: Context | None = None, result: Conversion | None = None,
                 csv_path: Path | None = None, report_path: Path | None = None,
                 stop: Event | None = None) -> None:
        super().__init__()
        self.kind, self.state = kind, state
        self.path, self.context, self.result = path, context, result
        self.csv_path, self.report_path, self.stop = csv_path, report_path, stop

    @Slot()
    def execute(self) -> None:
        try:
            if self.kind == "detect":
                assert self.path is not None
                raw = self.path.read_bytes()
                source = read_statement(self.path, raw)
                self.state["value"] = (source, sha256(raw).hexdigest())
            elif self.kind == "convert":
                assert self.path is not None and self.context is not None
                if self.stop is not None and self.stop.is_set():
                    self.state["cancelled"] = True
                else:
                    converted = convert(self.path, self.context)
                    self.state["value"] = converted
            elif self.kind == "save":
                assert self.result is not None and self.csv_path is not None
                assert self.report_path is not None
                # A paired save is non-cancellable; it owns its cleanup/commit.
                save_candidate(self.result, self.csv_path, self.report_path)
                self.state["value"] = (self.csv_path, self.report_path)
            else:
                raise RuntimeError("Unsupported GUI background operation")
        except Exception as exc:
            self.state["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            self.finished.emit()

class MainWindow(QMainWindow):
    conversion_done = Signal()
    detection_done = Signal()
    save_done = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.source: Path | None = None
        self.result: Conversion | None = None
        self._thread: QThread | None = None
        self._worker: _Job | None = None
        self._stop: Event | None = None
        self._job_state: dict | None = None
        self._selected_digest: str | None = None
        self._approved_digest: str | None = None
        self._saved = False
        self._last_detail = ""
        self._presentation_ready = False
        self.setWindowTitle("Bank2Odoo | تبدیل گزارش بانک")
        self.resize(940, 830)
        self.setMinimumSize(600, 480)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._build()
        self._configure_presentation()
        self._presentation_ready = True
        self._update_units()
        self._set_message("آماده: ابتدا فایل گزارش بانک را انتخاب کنید.")

    def _build(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll = scroll
        self.setCentralWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(26, 24, 26, 28)
        root.setSpacing(19)

        self.heading = QLabel("آماده‌سازی گردش بانک برای Odoo")
        root.addWidget(self.heading)
        lead = QLabel("Bank2Odoo  |  انتخاب فایل ← تأیید مالی ← تبدیل ← بررسی ← ذخیره")
        lead.setWordWrap(True)
        root.addWidget(lead)
        notice_panel = QFrame()
        notice_panel.setFrameShape(QFrame.Shape.StyledPanel)
        notice_panel.setAutoFillBackground(True)
        self.notice_panel = notice_panel
        notice_layout = QVBoxLayout(notice_panel)
        notice_layout.setContentsMargins(14, 10, 14, 10)
        warning = QLabel("فقط تهیه نامزد بررسی؛ این برنامه هیچ اطلاعاتی را وارد Odoo نمی‌کند و تأیید حسابداری نمی‌دهد.")
        warning.setWordWrap(True)
        notice_layout.addWidget(warning)
        root.addWidget(notice_panel)

        source_box = QGroupBox("۱. انتخاب گزارش بانکی")
        source_layout = QVBoxLayout(source_box)
        source_layout.setContentsMargins(18, 28, 18, 18)
        source_layout.setSpacing(12)
        source_row = QHBoxLayout()
        source_row.setSpacing(12)
        self.select_button = QPushButton("انتخاب فایل…")
        self.select_button.setMinimumHeight(40)
        self.select_button.clicked.connect(self._browse_source)
        source_row.addWidget(self.select_button)
        self.path_field = QLineEdit()
        self.path_field.setReadOnly(True)
        self.path_field.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.path_field.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.path_field.setMinimumHeight(40)
        self.path_field.setPlaceholderText("هنوز فایلی انتخاب نشده است")
        self.path_field.setAccessibleName("مسیر فایل انتخاب‌شده")
        source_row.addWidget(self.path_field, 1)
        source_layout.addLayout(source_row)
        self.detected = QLabel("بانک/قالب: هنوز فایلی بررسی نشده است.")
        self.detected.setWordWrap(True)
        source_layout.addWidget(self.detected)
        root.addWidget(source_box)

        context_box = QGroupBox("۲. اطلاعات مالی — با مسئولیت حسابدار")
        context_layout = QVBoxLayout(context_box)
        context_layout.setContentsMargins(18, 28, 18, 18)
        context_layout.setSpacing(13)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        context_layout.addLayout(form)
        self.source_unit = QComboBox()
        self.target_unit = QComboBox()
        for combo in (self.source_unit, self.target_unit):
            combo.addItem("انتخاب واحد…", None)
            combo.addItem("ریال (IRR)", "IRR")
            combo.addItem("تومان (TOMAN)", "TOMAN")
            combo.setAccessibleName("واحد پول")
            combo.setMinimumHeight(38)
            combo.setMaximumWidth(390)
            combo.currentIndexChanged.connect(self._context_changed)
        form.addRow("واحد پول فایل بانک:", self.source_unit)
        form.addRow("واحد پول ژورنال مقصد:", self.target_unit)
        self.journal = QLineEdit()
        self.journal.setMinimumHeight(38)
        self.journal.setMaximumWidth(480)
        self.journal.setPlaceholderText("نام ژورنال بانکی انتخاب‌شده در Odoo")
        self.journal.setAccessibleName("ژورنال بانکی")
        self.journal.textChanged.connect(self._context_changed)
        form.addRow("نام ژورنال بانکی:", self.journal)
        self.precision = QSpinBox()
        self.precision.setRange(0, 9)
        self.precision.setMinimumHeight(38)
        self.precision.setMaximumWidth(150)
        self.precision.setToolTip("دقت اعشاری واقعی ارز ژورنال را با حسابدار تأیید کنید. گردکردن انجام نمی‌شود.")
        self.precision.valueChanged.connect(self._context_changed)
        form.addRow("اعشار ارز مقصد (۰ تا ۹):", self.precision)
        self.factor = QLineEdit()
        self.factor.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.factor.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.factor.setMinimumHeight(38)
        self.factor.setMaximumWidth(260)
        self.factor.setPlaceholderText("برای واحدهای متفاوت ضریب را وارد کنید")
        self.factor.setAccessibleName("ضریب تبدیل تأییدشده")
        self.factor.textChanged.connect(self._context_changed)
        form.addRow("ضریب تبدیل تأییدشده:", self.factor)
        self.factor_help = QLabel("واحدها را انتخاب کنید؛ ضریب هرگز از فایل بانک حدس زده نمی‌شود.")
        self.factor_help.setWordWrap(True)
        form.addRow("", self.factor_help)
        approval_panel = QFrame()
        approval_panel.setFrameShape(QFrame.Shape.StyledPanel)
        approval_panel.setAutoFillBackground(True)
        self.approval_panel = approval_panel
        approval_layout = QVBoxLayout(approval_panel)
        approval_layout.setContentsMargins(16, 8, 16, 12)
        approval_layout.setSpacing(2)
        self.approved = _FullRowCheckBox("اطلاعات مالی بالا را شخصاً بررسی و تأیید کرده‌ام.")
        self._approval_indicator_style = _ApprovalIndicatorStyle(self.approved.style().objectName())
        self.approved.setStyle(self._approval_indicator_style)
        self.approved.setMinimumHeight(52)  # Full label and empty space are clickable.
        self.approved.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.approved.setCursor(Qt.CursorShape.PointingHandCursor)
        self.approved.setAccessibleName("تأیید صریح اطلاعات مالی")
        self.approved.setToolTip("با کلیک یا کلید فاصله تأیید کنید؛ تغییر اطلاعات آن را لغو می‌کند.")
        self.approved.toggled.connect(self._approval_changed)
        approval_layout.addWidget(self.approved)
        approval_hint = QLabel(
            "بانک، واحدهای مبدأ و مقصد، ژورنال، دقت اعشار و ضریب احتمالی را با مدارک واقعی تطبیق دهید."
        )
        approval_hint.setWordWrap(True)
        approval_layout.addWidget(approval_hint)
        context_layout.addWidget(approval_panel)
        root.addWidget(context_box)

        review_box = QGroupBox("۳. تبدیل و بررسی نتیجه")
        review_layout = QVBoxLayout(review_box)
        review_layout.setContentsMargins(18, 28, 18, 18)
        review_layout.setSpacing(12)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.convert_button = QPushButton("اعتبارسنجی و تبدیل")
        self.convert_button.setMinimumHeight(44)
        self.convert_button.clicked.connect(self.start_conversion)
        actions.addWidget(self.convert_button)
        self.cancel_button = QPushButton("درخواست توقف")
        self.cancel_button.setMinimumHeight(40)
        self.cancel_button.clicked.connect(self.cancel_conversion)
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        review_layout.addLayout(actions)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setVisible(False)
        self.busy.setAccessibleName("پردازش در حال اجرا")
        review_layout.addWidget(self.busy)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        review_layout.addWidget(self.status)
        self.summary = QLabel("هنوز خروجی برای بررسی تولید نشده است.")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setMinimumHeight(42)
        review_layout.addWidget(self.summary)
        self.details_button = QPushButton("نمایش جزئیات فنی")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_details)
        review_layout.addWidget(self.details_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.details.setVisible(False)
        self.details.setMinimumHeight(110)
        self.details.setAccessibleName("جزئیات فنی تبدیل و کنترل")
        review_layout.addWidget(self.details)
        root.addWidget(review_box)

        save_box = QGroupBox("۴. ذخیره هم‌زمان فایل نامزد و گزارش خصوصی")
        save_layout = QVBoxLayout(save_box)
        save_layout.setContentsMargins(18, 28, 18, 18)
        save_layout.setSpacing(12)
        output_row = QHBoxLayout()
        output_row.setSpacing(12)
        self.output_directory = QLineEdit()
        self.output_directory.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.output_directory.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.output_directory.setMinimumHeight(40)
        self.output_directory.setPlaceholderText("هنوز پوشه‌ای انتخاب نشده است")
        self.output_directory.setAccessibleName("پوشه خصوصی خروجی")
        self.output_directory.setReadOnly(True)
        output_row.addWidget(self.output_directory, 1)
        self.directory_button = QPushButton("انتخاب پوشه…")
        self.directory_button.setMinimumHeight(40)
        self.directory_button.clicked.connect(self._browse_directory)
        output_row.addWidget(self.directory_button)
        save_layout.addLayout(output_row)
        self.save_button = QPushButton("ذخیره CSV و گزارش کنترل")
        self.save_button.setMinimumHeight(44)
        self.save_button.clicked.connect(self.save_files)
        self.save_button.setEnabled(False)
        save_layout.addWidget(self.save_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.saved_paths = QLabel("هر دو فایل باید در یک پوشه خصوصی و بیرون از پوشه برنامه ذخیره شوند.")
        self.saved_paths.setWordWrap(True)
        self.saved_paths.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        save_layout.addWidget(self.saved_paths)
        next_step = QLabel(GENERAL_REVIEW)
        next_step.setWordWrap(True)
        save_layout.addWidget(next_step)
        root.addWidget(save_box)
        root.addStretch(1)

    def _apply_surface_palette(self) -> None:
        """Pair paint surfaces with their text roles from the current Qt palette."""
        palette = QApplication.palette()
        card_bg = palette.color(QPalette.ColorRole.Base)
        card_fg = palette.color(QPalette.ColorRole.Text)
        border = palette.color(QPalette.ColorRole.Mid)
        for card in self.findChildren(QGroupBox):
            # Qt style sheets do not reliably propagate foreground roles to
            # children. A widget palette does, so both must use the same pair.
            card_palette = QPalette(palette)
            card_palette.setColor(QPalette.ColorRole.Window, card_bg)
            card_palette.setColor(QPalette.ColorRole.WindowText, card_fg)
            card.setPalette(card_palette)
            card.setStyleSheet(f"""
                QGroupBox {{ background: {card_bg.name()}; color: {card_fg.name()};
                             border: 1px solid {border.name()};
                             border-radius: 10px; margin-top: 16px; }}
                QGroupBox::title {{ subcontrol-origin: margin;
                                    subcontrol-position: top right;
                                    padding: 0 8px; color: {card_fg.name()};
                                    font-weight: 600; }}
            """)

        # These two nested surfaces use the native Window/WindowText pair,
        # contrasting with their surrounding Base/Text cards. Controls retain
        # their own Qt style; no QCheckBox/QComboBox/QPushButton QSS is added.
        for panel in (self.notice_panel, self.approval_panel):
            panel.setPalette(QPalette(palette))

        # Status meaning is already spelled out in text. Avoid the old
        # hardcoded navy/red/green on a potentially dark card background.
        self.status.setPalette(QPalette(self.status.parentWidget().palette()))

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (self._presentation_ready
                and event.type() in (QEvent.Type.PaletteChange,
                                     QEvent.Type.ApplicationPaletteChange,
                                     QEvent.Type.StyleChange)):
            # Defer until Qt has finished propagating application palette/style
            # changes; avoid re-polishing a group during its change event.
            QTimer.singleShot(0, self._apply_surface_palette)

    def _configure_presentation(self) -> None:
        """Local card chrome with colors derived from the native Qt palette."""
        self._apply_surface_palette()
        base_font = QFont(self.font())
        base_font.setPointSize(11)
        self.setFont(base_font)
        title_font = QFont(base_font)
        title_font.setPointSize(18)
        title_font.setWeight(QFont.Weight.DemiBold)
        self.heading.setFont(title_font)
        action_font = QFont(base_font)
        action_font.setWeight(QFont.Weight.DemiBold)
        for widget in (self.convert_button, self.save_button, self.approved, self.status):
            widget.setFont(action_font)

    def _toggle_details(self, visible: bool) -> None:
        self.details.setVisible(visible)
        self.details_button.setText("پنهان‌کردن جزئیات فنی" if visible else "نمایش جزئیات فنی")

    def _set_message(self, message: str, detail: str = "") -> None:
        self.status.setText(message)
        self._last_detail = detail
        self.details.setPlainText(detail or "جزئیات بیشتری برای نمایش وجود ندارد.")

    def _invalidate(self) -> None:
        self.result = None
        self._saved = False
        self.save_button.setEnabled(False)
        self.saved_paths.setText("هنوز خروجی جدیدی ذخیره نشده است.")
        self.summary.setText("پس از تأیید زمینه مالی، تبدیل را اجرا کنید.")

    def _revoke_approval(self) -> None:
        self._approved_digest = None
        self.approved.blockSignals(True)
        self.approved.setChecked(False)
        self.approved.blockSignals(False)

    def _context_changed(self, *_args: object) -> None:
        self._revoke_approval()
        self._update_units()
        self._invalidate()

    def _approval_changed(self, checked: bool) -> None:
        if checked and self.source is None:
            self._revoke_approval()
        else:
            self._approved_digest = self._selected_digest if checked else None
        self._invalidate()

    def _update_units(self) -> None:
        left, right = self.source_unit.currentData(), self.target_unit.currentData()
        differs = left is not None and right is not None and left != right
        self.factor.setEnabled(differs)
        if not differs:
            self.factor.blockSignals(True)
            self.factor.clear()
            self.factor.blockSignals(False)
        if differs:
            example = "10" if left == "TOMAN" else "0.1"
            self.factor_help.setText(
                f"واحدها متفاوت‌اند؛ ضریب {example} فقط یک نمونه محاسباتی است، نه تأیید مالی. ضریب را با مدارک بررسی و وارد کنید."
            )
        else:
            self.factor_help.setText("برای واحدهای یکسان ضریب لازم نیست؛ واحدهای هر دو طرف باید تأیید شوند.")

    def _browse_source(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "انتخاب صورت‌حساب بانکی", "",
                                               "گزارش‌های بانکی پشتیبانی‌شده (*.xls *.csv);;همه فایل‌ها (*)")
        if name:
            self.set_source(Path(name))

    def set_source(self, path: Path) -> None:
        if self._thread is not None:
            return
        # Re-selecting even the exact same path revokes the old approval.
        self._revoke_approval()
        self.source = None
        self._selected_digest = None
        self._invalidate()
        self.path_field.setText(str(path))
        self.detected.setText("در حال بررسی قالب…")
        self._set_message("در حال خواندن و شناسایی فایل؛ لطفاً پایان بررسی را مشاهده کنید.")
        self._begin("detect", path=path)

    def _begin(self, kind: str, **kwargs: object) -> None:
        if self._thread is not None:
            raise RuntimeError("A file operation is already active")
        thread = QThread(self)
        state: dict = {"kind": kind, "path": kwargs.get("path"), "value": None,
                       "error": None, "cancelled": False}
        worker = _Job(kind, state, **kwargs)
        worker.moveToThread(thread)
        thread.started.connect(worker.execute)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(worker.deleteLater)
        self._job_state, self._thread, self._worker = state, thread, worker
        self._set_busy(True)
        thread.start()

    def _context(self) -> Context:
        if self.source is None:
            raise StatementError("No supported input selected")
        if (not self.approved.isChecked() or self._selected_digest is None
                or self._approved_digest != self._selected_digest):
            raise StatementError("Financial inputs require approval for this exact selected statement")
        left, right = self.source_unit.currentData(), self.target_unit.currentData()
        if left is None or right is None:
            raise StatementError("Explicit supported source/target unit required")
        factor = None
        if left != right:
            value = self.factor.text().strip()
            if not value:
                raise StatementError("Different units require an explicitly approved factor")
            try:
                factor = Decimal(value)
            except InvalidOperation as exc:
                raise StatementError("Invalid approved factor") from exc
        context = Context(left, right, self.journal.text().strip(), self.precision.value(), factor)
        context.factor()
        return context

    def _missing_input_guidance(self) -> tuple[QWidget | None, str | None]:
        """Point to the first visibly missing input; engine validation stays authoritative."""
        if self.source is None:
            return self.select_button, "ابتدا یک گزارش بانکی پشتیبانی‌شده انتخاب کنید."
        if self.source_unit.currentData() is None:
            return self.source_unit, "واحد پول فایل بانک را انتخاب کنید."
        if self.target_unit.currentData() is None:
            return self.target_unit, "واحد پول ژورنال مقصد را انتخاب کنید."
        if not self.journal.text().strip():
            return self.journal, "نام ژورنال بانکی مقصد را وارد کنید."
        if (self.source_unit.currentData() != self.target_unit.currentData()
                and not self.factor.text().strip()):
            return self.factor, "ضریب تبدیل تأییدشده را وارد کنید."
        if not self.approved.isChecked():
            return self.approved, "اطلاعات مالی را بررسی کنید و سپس تأیید صریح را فعال کنید."
        return None, None

    def start_conversion(self) -> None:
        if self._thread is not None:
            return
        self._invalidate()
        try:
            context = self._context()
        except StatementError as exc:
            widget, guidance = self._missing_input_guidance()
            self._set_message("تبدیل آغاز نشد: " + (guidance or human_error(str(exc))),
                              str(exc))
            if widget is not None:
                self.scroll.ensureWidgetVisible(widget)
                widget.setFocus()
            return
        assert self.source is not None
        self._stop = Event()
        self._set_message("در حال خواندن و کنترل گردش‌ها… درصد پیشرفت قابل اندازه‌گیری نیست.")
        self._begin("convert", path=self.source, context=context, stop=self._stop)

    def _set_busy(self, active: bool) -> None:
        self.busy.setVisible(active)
        self.cancel_button.setEnabled(active and self._job_state is not None
                                      and self._job_state["kind"] == "convert")
        for widget in (self.select_button, self.source_unit, self.target_unit, self.journal,
                       self.precision, self.factor, self.approved, self.convert_button,
                       self.directory_button):
            widget.setEnabled(not active)
        if not active:
            self._update_units()
        self.save_button.setEnabled(not active and self.result is not None and not self._saved)

    def cancel_conversion(self) -> None:
        if (self._thread is not None and self._job_state is not None
                and self._job_state["kind"] == "convert" and self._stop is not None):
            self._stop.set()
            self.cancel_button.setEnabled(False)
            self._set_message("درخواست توقف ثبت شد؛ پس از پایان مرحله فعلی هیچ نامزد جدیدی نمایش داده نمی‌شود.")

    @Slot(object)
    def _success(self, result: Conversion) -> None:
        if self._stop is not None and self._stop.is_set():
            self._cancelled()
            return
        self.result = result
        good = result.balance_status.startswith("PASS")
        check = ("منطبق در انتقال‌های قابل‌آزمون؛ هنوز تأیید حسابدار نیست."
                 if good else "احراز نشده؛ لزوماً مغایرت نیست. بررسی حسابدار لازم است.")
        self.summary.setText(
            f"بانک: {BANK_LABELS[result.bank]}  |  تعداد: {latin(len(result.rows))} گردش\n"
            f"برداشت: {latin(format(result.debit_total, 'f'))} {result.source_unit}  |  "
            f"واریز: {latin(format(result.credit_total, 'f'))} {result.source_unit}\n"
            f"خالص: {latin(format(result.net, 'f'))} {result.source_unit}  |  "
            f"خالص مقصد: {latin(format(exact_sum(m.converted for m in result.rows), 'f'))} {result.target_unit}\n"
            f"کنترل مانده: {check}\n"
            f"موارد نیازمند بررسی: {latin(len(result.issues))}"
            + ("\n" + "\n".join("• " + issue_label(x) for x in result.issues[:4])
               if result.issues else "")
        )
        self._set_message("تبدیل انجام شد: نامزد بررسی تهیه شده، اما هنوز ذخیره یا تأیید نشده است.",
                          "Balance: " + result.balance_status + "\n" + "\n".join(result.issues))
        self.save_button.setEnabled(True)

    @Slot(str)
    def _failed(self, detail: str) -> None:
        self._set_message("خطا: " + human_error(detail), detail)
        self.summary.setText("خروجی تولید نشد؛ فایل نامزد قابل ذخیره نیست.")
 

    @Slot()
    def _cancelled(self) -> None:
        self._set_message("توقف درخواست‌شده انجام شد؛ خروجی جدیدی تولید یا ذخیره نشد.")


    def _wait_for_thread(self, thread: QThread, timeout_ms: int) -> bool:
        """Join boundary, kept separate so unsuccessful waits can be tested."""
        return thread.wait(timeout_ms)

    @Slot()
    def _thread_finished(self) -> None:
        """Only the matching worker may publish its outcome after a native join."""
        state = self._job_state
        thread = self._thread
        if state is None or thread is None or self.sender() is not thread:
            return  # A late signal from another worker cannot publish an outcome.
        self._join_finished_thread(thread, state, 5000)

    def _join_finished_thread(self, thread: QThread, state: dict,
                              timeout_ms: int) -> None:
        if self._thread is not thread or self._job_state is not state:
            return  # A stale timeout cannot complete a newer operation.
        if not self._wait_for_thread(thread, timeout_ms):
            self._set_message(
                "خطا: پایان کامل پردازش هنوز تأیید نشده است؛ عملیات جدید مسدود "
                "می‌ماند و برنامه به‌صورت خودکار دوباره بررسی می‌کند."
            )
            # Retry without blocking the GUI. Keep ownership until a real join;
            # an indefinitely unsuccessful join remains safely blocked.
            QTimer.singleShot(
                250, lambda: self._join_finished_thread(thread, state, 0)
            )
            return
        # The QThread lives in the GUI thread. Unlike the worker's standard
        # finished -> deleteLater connection, its C++ deletion must not be
        # scheduled until Qt confirms native thread termination.
        thread.deleteLater()
        kind, value, error = state["kind"], state["value"], state["error"]
        stopped = self._stop is not None and self._stop.is_set()
        self._thread, self._worker, self._stop, self._job_state = None, None, None, None
        if kind == "detect":
            if error is not None:
                self.source = None
                self._selected_digest = None
                self.detected.setText("بانک/قالب: شناسایی نشد.")
                self._set_message("خطا: " + human_error(error), error)
            else:
                source, digest = value
                self.source = state["path"]
                self._selected_digest = digest
                self.detected.setText(
                    f"شناسایی‌شده: {BANK_LABELS[source.bank]} | {latin(len(source.rows))} گردش | "
                    f"قالب: {latin(source.encoding)} / {latin(source.separator)} (فقط ساختار، نه واحد پول)"
                )
                self._set_message("فایل شناسایی شد. اکنون اطلاعات مالی را خودتان تأیید کنید.")
        elif kind == "convert":
            if stopped or state["cancelled"]:
                self._cancelled()
            elif error is not None:
                self._failed(error)
            elif (self._selected_digest is None
                  or self._approved_digest != self._selected_digest
                  or self.source is None or value.sha256 != self._selected_digest):
                # Content changed between detection and conversion, or
                # approval no longer belongs to the selected source bytes.
                self._revoke_approval()
                self.source = None
                self._selected_digest = None
                self._invalidate()
                self.detected.setText("هویت فایل تغییر کرده؛ شناسایی مجدد ضروری است.")
                self._set_message(
                    "فایل پس از شناسایی تغییر کرده است؛ نامزد پذیرفته نشد. "
                    "فایل را دوباره انتخاب و اطلاعات مالی را دوباره تأیید کنید."
                )
            else:
                self._success(value)
        elif kind == "save":
            if error is not None:
                self.saved_paths.setText("ذخیره کامل نشد؛ فایل‌ها را در پوشه مقصد بررسی کنید.")
                self._set_message("خطای ذخیره: " + human_error(error, saving=True), error)
            else:
                csv_path, report_path = value
                self._saved = True
                self.saved_paths.setText(
                    f"دو فایل ایجاد شدند:\nCSV: {latin(csv_path)}\nگزارش کنترل خصوصی: {latin(report_path)}"
                )
                self._set_message("ذخیره هر دو فایل موفق بود. نامزد هنوز مجوز ورود به Odoo نیست.")
        self._set_busy(False)
        if kind == "detect":
            self.detection_done.emit()
        elif kind == "convert":
            self.conversion_done.emit()
        else:
            self.save_done.emit()

    def _browse_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "پوشه خصوصی برای دو فایل خروجی")
        if folder:
            self.output_directory.setText(folder)

    def save_files(self) -> None:
        if self._thread is not None:
            return
        if self.result is None or self._saved:
            self._set_message("ابتدا تبدیل موفق را تکمیل کنید؛ هیچ خروجی تازه‌ای ذخیره نشد.")
            return
        folder_text = self.output_directory.text().strip()
        if not folder_text:
            self._set_message("خطا: پیش از ذخیره یک پوشه خصوصی انتخاب کنید.")
            return
        folder = Path(folder_text)
        assert self.source is not None
        safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.source.stem)[:48]
        prefix = f"Bank2Odoo_{safe_stem or 'statement'}_{self.result.sha256[:10]}"
        csv_path = folder / f"{prefix}_candidate.csv"
        report_path = folder / f"{prefix}_control.txt"
        self._set_message("در حال ذخیره هم‌زمان نامزد و گزارش خصوصی؛ تا پایان عملیات پنجره را نبندید.")
        self._begin("save", result=self.result, csv_path=csv_path, report_path=report_path)

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            QMessageBox.information(self, "پردازش در حال اجرا",
                                    "عملیات فایل در حال اجرا است. لطفاً تا پایان آن پنجره را باز نگه دارید.\n"
                                    "در زمان تبدیل می‌توانید درخواست توقف بدهید؛ ذخیره در میانه قطع نمی‌شود.")
            event.ignore()
            return
        event.accept()


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    configure_application(app)
    window = MainWindow()
    window.show()
    return app.exec()
