"""
ui/order_panel.py
- Fix #1: auto-fetch LTP when symbol typed (debounced 800ms), populate price field
- Fix #3: correct price/trigger strings per order type (MARKET → "0", LIMIT → float)
- Place order runs in background thread
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QDoubleSpinBox,
    QSpinBox, QGroupBox, QFormLayout
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer
from core.api_client import APIClient


# ── Workers ─────────────────────────────────────────────────────────────────

class LTPWorker(QThread):
    done  = pyqtSignal(float)
    error = pyqtSignal(str)

    def __init__(self, exchange: str, symbol: str):
        super().__init__()
        self.exchange = exchange
        self.symbol   = symbol

    def run(self):
        r = APIClient.get().get_ltp([f"{self.exchange}:{self.symbol}"])
        if not r["success"]:
            self.error.emit(r.get("error", "LTP failed"))
            return
        # Response: {"data": {"NSE:INFY": {"last_price": 1234.5, ...}}}
        raw = r.get("data", {})
        instruments = raw.get("data", raw) if isinstance(raw, dict) else raw
        ltp = 0.0
        if isinstance(instruments, dict):
            for v in instruments.values():
                if isinstance(v, dict):
                    ltp = float(v.get("last_price") or v.get("ltp") or 0)
                    break
        if ltp > 0:
            self.done.emit(ltp)
        else:
            self.error.emit("Price unavailable")


class PlaceOrderWorker(QThread):
    success = pyqtSignal(dict)
    failure = pyqtSignal(str)

    def __init__(self, kwargs: dict):
        super().__init__()
        self.kwargs = kwargs

    def run(self):
        r = APIClient.get().place_order(**self.kwargs)
        if r["success"]:
            self.success.emit(r)
        else:
            self.failure.emit(r.get("error", "Order failed"))


# ── Panel ────────────────────────────────────────────────────────────────────

class OrderPanel(QWidget):
    order_placed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._side = "BUY"
        self._ltp  = 0.0
        self._ltp_timer = QTimer(self)
        self._ltp_timer.setSingleShot(True)
        self._ltp_timer.timeout.connect(self._fetch_ltp)
        self._build_ui()

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(20)

        # ── Form ────────────────────────────────────────────────
        form_box = QGroupBox("Place New Order")
        form_box.setStyleSheet(
            "QGroupBox{color:#AAAACC;font-weight:bold;font-size:13px;"
            "border:1px solid #252538;border-radius:8px;margin-top:10px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;}"
        )
        form_box.setMaximumWidth(480)
        form = QFormLayout(form_box)
        form.setSpacing(12)
        form.setContentsMargins(16, 20, 16, 16)

        # Symbol row with inline LTP badge
        sym_row = QWidget()
        sym_lay = QHBoxLayout(sym_row)
        sym_lay.setContentsMargins(0, 0, 0, 0)
        sym_lay.setSpacing(8)
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("e.g. INFY, TCS")
        self.symbol_input.textChanged.connect(self._on_symbol_changed)
        sym_lay.addWidget(self.symbol_input, 1)

        self.ltp_badge = QLabel("LTP  —")
        self.ltp_badge.setFixedWidth(110)
        self.ltp_badge.setAlignment(Qt.AlignCenter)
        self.ltp_badge.setStyleSheet(
            "color:#666680;font-size:12px;padding:4px 8px;"
            "background:#1C1C2A;border:1px solid #353550;border-radius:4px;"
        )
        sym_lay.addWidget(self.ltp_badge)
        form.addRow("Symbol *", sym_row)

        # Exchange — re-trigger LTP on change
        self.exchange_combo = QComboBox()
        self.exchange_combo.addItems(["NSE", "BSE"])
        self.exchange_combo.currentTextChanged.connect(self._on_symbol_changed)
        form.addRow("Exchange", self.exchange_combo)

        # BUY / SELL
        side_w = QWidget()
        side_l = QHBoxLayout(side_w)
        side_l.setContentsMargins(0, 0, 0, 0)
        side_l.setSpacing(8)
        self.buy_btn  = QPushButton("BUY")
        self.sell_btn = QPushButton("SELL")
        self.buy_btn.setCheckable(True)
        self.sell_btn.setCheckable(True)
        self.buy_btn.clicked.connect(lambda: self._set_side("BUY"))
        self.sell_btn.clicked.connect(lambda: self._set_side("SELL"))
        side_l.addWidget(self.buy_btn)
        side_l.addWidget(self.sell_btn)
        form.addRow("Side", side_w)
        self._set_side("BUY")

        # Order type
        self.order_type_combo = QComboBox()
        self.order_type_combo.addItems(["MARKET", "LIMIT", "SL", "SL-M"])
        self.order_type_combo.currentTextChanged.connect(self._update_price_visibility)
        form.addRow("Order Type", self.order_type_combo)

        # Product / Variety / Validity
        self.product_combo  = QComboBox(); self.product_combo.addItems(["CNC", "MIS", "NRML"])
        self.variety_combo  = QComboBox(); self.variety_combo.addItems(["regular", "amo"])
        self.validity_combo = QComboBox(); self.validity_combo.addItems(["DAY", "IOC"])
        form.addRow("Product",  self.product_combo)
        form.addRow("Variety",  self.variety_combo)
        form.addRow("Validity", self.validity_combo)

        # Quantity
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 1_000_000)
        self.qty_spin.setValue(1)
        form.addRow("Quantity *", self.qty_spin)

        # Price (LIMIT / SL only)
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 1e7)
        self.price_spin.setDecimals(2)
        self.price_spin.setPrefix("₹ ")
        self._price_lbl = QLabel("Price")
        form.addRow(self._price_lbl, self.price_spin)

        # Trigger (SL / SL-M only)
        self.trigger_spin = QDoubleSpinBox()
        self.trigger_spin.setRange(0, 1e7)
        self.trigger_spin.setDecimals(2)
        self.trigger_spin.setPrefix("₹ ")
        self._trigger_lbl = QLabel("Trigger Price")
        form.addRow(self._trigger_lbl, self.trigger_spin)

        self._update_price_visibility("MARKET")

        # Buttons
        btn_w = QWidget()
        btn_l = QHBoxLayout(btn_w)
        btn_l.setContentsMargins(0, 0, 0, 0)
        btn_l.setSpacing(10)
        self.submit_btn = QPushButton("Place Order")
        self.submit_btn.setFixedHeight(42)
        self.submit_btn.setStyleSheet(
            "background:#1A5A30;color:#50DD80;border-color:#2A7040;font-weight:bold;font-size:13px;")
        self.submit_btn.clicked.connect(self._place_order)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(42)
        clear_btn.clicked.connect(self._clear_form)
        btn_l.addWidget(self.submit_btn)
        btn_l.addWidget(clear_btn)
        form.addRow("", btn_w)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setMinimumHeight(20)
        form.addRow("", self.status_lbl)

        outer.addWidget(form_box)

        # ── Quick Reference ─────────────────────────────────────
        ref_box = QGroupBox("Quick Reference")
        ref_box.setStyleSheet(
            "QGroupBox{color:#AAAACC;font-weight:bold;font-size:13px;"
            "border:1px solid #252538;border-radius:8px;margin-top:10px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;}"
        )
        ref_lay = QVBoxLayout(ref_box)
        ref_lay.setContentsMargins(16, 20, 16, 16)
        ref_lbl = QLabel("""
<style>body{color:#AAAACC;font-size:12px;}b{color:#FFF;}.s{color:#5078DC;font-weight:bold;margin-top:8px;}td{padding:3px 12px 3px 0;}</style>
<p class="s">Order Types</p>
<table>
<tr><td><b>MARKET</b></td><td>Best available price immediately</td></tr>
<tr><td><b>LIMIT</b></td><td>At your specified price or better</td></tr>
<tr><td><b>SL</b></td><td>Stop-loss with limit price</td></tr>
<tr><td><b>SL-M</b></td><td>Stop-loss at market</td></tr>
</table>
<p class="s">Product Types</p>
<table>
<tr><td><b>CNC</b></td><td>Delivery (hold overnight)</td></tr>
<tr><td><b>MIS</b></td><td>Intraday (auto square-off)</td></tr>
<tr><td><b>NRML</b></td><td>F&amp;O overnight</td></tr>
</table>
<p class="s">Tips</p>
<ul>
<li>LTP auto-loads when you type the symbol</li>
<li>MARKET: price &amp; trigger auto-set to 0</li>
<li>SL/SL-M: trigger price required</li>
</ul>""")
        ref_lbl.setTextFormat(Qt.RichText)
        ref_lbl.setWordWrap(True)
        ref_lbl.setStyleSheet("background:#0E0E18;padding:12px;border-radius:4px;")
        ref_lay.addWidget(ref_lbl)
        ref_lay.addStretch()
        outer.addWidget(ref_box)
        outer.addStretch()

    # ── LTP auto-fetch ───────────────────────────────────────────

    def _on_symbol_changed(self):
        self._ltp_timer.start(800)  # debounce
        self.ltp_badge.setText("LTP  …")
        self.ltp_badge.setStyleSheet(
            "color:#888899;font-size:12px;padding:4px 8px;"
            "background:#1C1C2A;border:1px solid #353550;border-radius:4px;"
        )

    def _fetch_ltp(self):
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            self._reset_ltp_badge()
            return
        self._ltp_worker = LTPWorker(self.exchange_combo.currentText(), symbol)
        self._ltp_worker.done.connect(self._on_ltp)
        self._ltp_worker.error.connect(self._on_ltp_error)
        self._ltp_worker.start()

    def _on_ltp(self, ltp: float):
        self._ltp = ltp
        self.ltp_badge.setText(f"₹ {ltp:,.2f}")
        self.ltp_badge.setStyleSheet(
            "color:#40CC70;font-size:12px;font-weight:bold;padding:4px 8px;"
            "background:#0F2A1A;border:1px solid #1A5A30;border-radius:4px;"
        )
        # Pre-fill price field if order type needs it and field is still at zero
        ot = self.order_type_combo.currentText()
        if ot in ("LIMIT", "SL") and self.price_spin.value() == 0:
            self.price_spin.setValue(ltp)
        if ot in ("SL", "SL-M") and self.trigger_spin.value() == 0:
            self.trigger_spin.setValue(ltp)

    def _on_ltp_error(self, _err: str):
        self._ltp = 0.0
        self.ltp_badge.setText("LTP  N/A")
        self.ltp_badge.setStyleSheet(
            "color:#FF8800;font-size:12px;padding:4px 8px;"
            "background:#2A1A00;border:1px solid #5A3A00;border-radius:4px;"
        )

    def _reset_ltp_badge(self):
        self._ltp = 0.0
        self.ltp_badge.setText("LTP  —")
        self.ltp_badge.setStyleSheet(
            "color:#666680;font-size:12px;padding:4px 8px;"
            "background:#1C1C2A;border:1px solid #353550;border-radius:4px;"
        )

    # ── Price field visibility ───────────────────────────────────

    def _update_price_visibility(self, order_type: str):
        need_price   = order_type in ("LIMIT", "SL")
        need_trigger = order_type in ("SL", "SL-M")
        self.price_spin.setEnabled(need_price)
        self.trigger_spin.setEnabled(need_trigger)
        self._price_lbl.setStyleSheet("color:#AAAACC;" if need_price else "color:#555570;")
        self._trigger_lbl.setStyleSheet("color:#AAAACC;" if need_trigger else "color:#555570;")
        # Pre-fill with LTP when switching to a type that needs price
        if need_price and self.price_spin.value() == 0 and self._ltp:
            self.price_spin.setValue(self._ltp)
        if need_trigger and self.trigger_spin.value() == 0 and self._ltp:
            self.trigger_spin.setValue(self._ltp)

    def _set_side(self, side: str):
        self._side = side
        buy_active  = "background:#1A5A30;color:#50DD80;border-color:#2A7040;font-weight:bold;"
        sell_active = "background:#5A1A1A;color:#FF6060;border-color:#703030;font-weight:bold;"
        self.buy_btn.setChecked(side == "BUY")
        self.sell_btn.setChecked(side == "SELL")
        self.buy_btn.setStyleSheet(buy_active   if side == "BUY"  else "")
        self.sell_btn.setStyleSheet(sell_active if side == "SELL" else "")

    # ── Place order ──────────────────────────────────────────────

    def _place_order(self):
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            self._set_status("Symbol is required", error=True)
            return

        ot = self.order_type_combo.currentText()

        # Fix #3: build correct price / trigger strings per order type
        if ot == "MARKET":
            price         = "0"
            trigger_price = "0"
        elif ot == "LIMIT":
            price         = f"{self.price_spin.value():.2f}"
            trigger_price = "0"
        elif ot == "SL":
            price         = f"{self.price_spin.value():.2f}"
            trigger_price = f"{self.trigger_spin.value():.2f}"
        else:  # SL-M
            price         = "0"
            trigger_price = f"{self.trigger_spin.value():.2f}"

        kwargs = dict(
            variety            = self.variety_combo.currentText(),
            symbol             = symbol,
            exchange           = self.exchange_combo.currentText(),
            transaction_type   = self._side,
            order_type         = ot,
            quantity           = str(self.qty_spin.value()),
            product            = self.product_combo.currentText(),
            validity           = self.validity_combo.currentText(),
            price              = price,
            trigger_price      = trigger_price,
            disclosed_quantity = "0",   # required by SDK
            tag                = "",    # required by SDK
        )

        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Placing…")
        self._set_status("")

        self._order_worker = PlaceOrderWorker(kwargs)
        self._order_worker.success.connect(self._on_order_ok)
        self._order_worker.failure.connect(self._on_order_fail)
        self._order_worker.start()

    def _on_order_ok(self, result: dict):
        symbol = self.symbol_input.text().strip().upper()
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Place Order")
        self._set_status(f"✓  Order placed for {symbol}", error=False)
        self.order_placed.emit(result)

    def _on_order_fail(self, error: str):
        self.submit_btn.setEnabled(True)
        self.submit_btn.setText("Place Order")
        self._set_status(f"✗  {error}", error=True)
        self.order_placed.emit({"success": False, "error": error})

    def _set_status(self, msg: str, error: bool = True):
        color = "#FF6060" if error else "#50DD80"
        self.status_lbl.setText(
            f'<span style="color:{color};font-size:13px;">{msg}</span>')

    def _clear_form(self):
        self.symbol_input.clear()
        self.qty_spin.setValue(1)
        self.price_spin.setValue(0)
        self.trigger_spin.setValue(0)
        self._reset_ltp_badge()
        self.status_lbl.setText("")
        self._set_side("BUY")
        self.order_type_combo.setCurrentIndex(0)
