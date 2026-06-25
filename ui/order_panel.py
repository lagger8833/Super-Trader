"""
ui/order_panel.py

Key facts from mStock API docs:
- NSE equity symbol format : NSE:INFY-EQ  (always -EQ suffix)
- BSE equity symbol format : BSE:INFY-EQ  (also -EQ)
- F&O symbol format        : NFO:NIFTY25JUN26FUT  (exchange=NFO, symbol=NAME+DDMMMYY+TYPE)
- Instrument master        : GET /instruments/scriptmaster → CSV with all tradeable symbols

Layout:
- Left  : Order form (fixed width)
- Right : Vertical splitter → top=Equity, bottom=F&O
  Both panels are searchable; clicking fills the symbol + sets exchange
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QDoubleSpinBox,
    QSpinBox, QGroupBox, QFormLayout, QListWidget,
    QCompleter, QSplitter, QFrame, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer, QStringListModel
from PyQt5.QtGui import QColor
from core.api_client import APIClient

# ── Static equity list (NSE, -EQ suffix required by mStock API) ──────────────
# Shown until instruments API loads. Sorted alphabetically.
EQUITY_STOCKS = sorted([
    "ADANIPORTS-EQ","APOLLOHOSP-EQ","ASIANPAINT-EQ","AXISBANK-EQ",
    "BAJAJ-AUTO-EQ","BAJAJFINSV-EQ","BAJFINANCE-EQ","BERGEPAINT-EQ",
    "BHARTIARTL-EQ","BPCL-EQ","BRITANNIA-EQ","CIPLA-EQ","COALINDIA-EQ",
    "COLPAL-EQ","DABUR-EQ","DIVISLAB-EQ","DMART-EQ","DRREDDY-EQ",
    "EICHERMOT-EQ","GRASIM-EQ","HAVELLS-EQ","HCLTECH-EQ","HDFCBANK-EQ",
    "HDFCLIFE-EQ","HEROMOTOCO-EQ","HINDALCO-EQ","HINDUNILVR-EQ",
    "ICICIBANK-EQ","IDEA-EQ","INDUSINDBK-EQ","INFY-EQ","IOC-EQ",
    "IRCTC-EQ","ITC-EQ","JSWSTEEL-EQ","KOTAKBANK-EQ","LT-EQ",
    "MARICO-EQ","MARUTI-EQ","NESTLEIND-EQ","NYKAA-EQ","NTPC-EQ",
    "ONGC-EQ","PAYTM-EQ","PIDILITIND-EQ","POWERGRID-EQ","RELIANCE-EQ",
    "SBIN-EQ","SBILIFE-EQ","SUNPHARMA-EQ","TATAMOTORS-EQ","TATASTEEL-EQ",
    "TATACONSUM-EQ","TCS-EQ","TECHM-EQ","TITAN-EQ","ULTRACEMCO-EQ",
    "WIPRO-EQ","YESBANK-EQ","ZOMATO-EQ",
])

# Static F&O seed list — shows while live data loads from API
# Format: exchange|symbol|display  (pipe-separated for easy parsing)
FNO_SEED = [
    # Index futures (current month — update symbol date as needed)
    "NFO|NIFTY25JUN26FUT|NIFTY Jun 26 FUT",
    "NFO|BANKNIFTY25JUN26FUT|BANKNIFTY Jun 26 FUT",
    "NFO|FINNIFTY25JUN26FUT|FINNIFTY Jun 26 FUT",
    # Common stock futures
    "NFO|RELIANCE25JUN26FUT|RELIANCE Jun 26 FUT",
    "NFO|TCS25JUN26FUT|TCS Jun 26 FUT",
    "NFO|INFY25JUN26FUT|INFY Jun 26 FUT",
    "NFO|HDFCBANK25JUN26FUT|HDFCBANK Jun 26 FUT",
    "NFO|SBIN25JUN26FUT|SBIN Jun 26 FUT",
    "NFO|ICICIBANK25JUN26FUT|ICICIBANK Jun 26 FUT",
    "NFO|WIPRO25JUN26FUT|WIPRO Jun 26 FUT",
    "NFO|AXISBANK25JUN26FUT|AXISBANK Jun 26 FUT",
    "NFO|BAJFINANCE25JUN26FUT|BAJFINANCE Jun 26 FUT",
    "NFO|TATAMOTORS25JUN26FUT|TATAMOTORS Jun 26 FUT",
    "NFO|MARUTI25JUN26FUT|MARUTI Jun 26 FUT",
    "NFO|LT25JUN26FUT|LT Jun 26 FUT",
]


# ── Instrument master loader ──────────────────────────────────────────────────

class InstrumentLoader(QThread):
    """
    Loads the full instrument CSV from mStock API.
    GET /instruments/scriptmaster → CSV
    Emits list of "exchange|symbol|display" strings for F&O instruments.
    Falls back to FNO_SEED if the API fails.
    """
    fno_ready = pyqtSignal(list)   # list of "NFO|NIFTY25JUN26FUT|NIFTY Jun FUT"

    def run(self):
        try:
            resp = APIClient.get()._mconnect.get_instruments()
            # The SDK returns the CSV as a Response object or string
            raw = resp.text if hasattr(resp, "text") else str(resp)
            fno = self._parse_fno(raw)
            if fno:
                self.fno_ready.emit(fno)
            else:
                self.fno_ready.emit(FNO_SEED)
        except Exception:
            self.fno_ready.emit(FNO_SEED)

    def _parse_fno(self, csv_text: str) -> list:
        """
        Parse instrument CSV. Expected columns (mStock format):
        instrument_token, exchange_token, tradingsymbol, name,
        last_price, expiry, strike, tick_size, lot_size,
        instrument_type, segment, exchange
        Filter: exchange in (NFO, BFO), instrument_type in (FUT, CE, PE)
        """
        lines = csv_text.strip().splitlines()
        if len(lines) < 2:
            return []

        results = []
        try:
            header = [h.strip().lower() for h in lines[0].split(",")]
            sym_idx  = header.index("tradingsymbol")
            exch_idx = header.index("exchange")
            type_idx = header.index("instrument_type")
            exp_idx  = header.index("expiry") if "expiry" in header else -1
        except (ValueError, IndexError):
            return []

        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) <= max(sym_idx, exch_idx, type_idx):
                continue
            exch  = parts[exch_idx].strip()
            sym   = parts[sym_idx].strip()
            itype = parts[type_idx].strip().upper()

            if exch not in ("NFO", "BFO") or itype not in ("FUT", "CE", "PE"):
                continue

            expiry = parts[exp_idx].strip() if exp_idx >= 0 and exp_idx < len(parts) else ""
            display = f"{sym}  [{exch}]  {expiry}".strip()
            results.append(f"{exch}|{sym}|{display}")

        # Sort: FUT first, then CE/PE; alphabetical within each group
        fut = sorted([r for r in results if "FUT" in r.split("|")[1]])
        opt = sorted([r for r in results if "FUT" not in r.split("|")[1]])
        return fut + opt


# ── Workers ───────────────────────────────────────────────────────────────────

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


# ── Stock list widget ─────────────────────────────────────────────────────────

class StockListBox(QGroupBox):
    """
    Compact searchable list.
    Each item stores exchange|symbol|display in UserRole.
    Emitting: (exchange, symbol, display)
    """
    selected = pyqtSignal(str, str, str)   # exchange, symbol, display

    LIST_STYLE = """
        QListWidget {
            background:#0E0E18; border:1px solid #252538;
            color:#DCDCE6; font-size:12px;
        }
        QListWidget::item { padding:4px 8px; border-bottom:1px solid #1A1A28; }
        QListWidget::item:hover    { background:#1C1C2A; color:#FFFFFF; }
        QListWidget::item:selected { background:#252545; color:#FFFFFF; }
        QLineEdit {
            background:#1C1C2A; border:1px solid #353550; border-radius:3px;
            padding:4px 8px; color:#DCDCE6; font-size:11px;
        }
        QLineEdit:focus { border-color:#5078DC; }
    """

    def __init__(self, title: str, entries: list, parent=None):
        """entries: list of "EXCHANGE|SYMBOL|DISPLAY" or plain "SYMBOL-EQ" strings"""
        super().__init__(title, parent)
        self._all = entries
        self.setStyleSheet(
            "QGroupBox{color:#AAAACC;font-weight:bold;font-size:12px;"
            "border:1px solid #252538;border-radius:6px;margin-top:8px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 14, 6, 6)
        lay.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.textChanged.connect(self._filter)
        lay.addWidget(self._search)

        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_click)
        lay.addWidget(self._list)
        self.setStyleSheet(self.styleSheet() + self.LIST_STYLE)
        self._populate(entries)

    def _parse(self, entry: str):
        """Returns (exchange, symbol, display)"""
        parts = entry.split("|")
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        # Plain equity symbol like "INFY-EQ"
        return "NSE", entry, entry

    def _populate(self, entries: list):
        self._list.clear()
        for e in entries:
            _, sym, display = self._parse(e)
            from PyQt5.QtWidgets import QListWidgetItem
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, e)
            self._list.addItem(item)

    def _filter(self, text: str):
        q = text.strip().upper()
        if not q:
            self._populate(self._all)
            return
        filtered = [e for e in self._all if q in e.upper()]
        self._populate(filtered)

    def _on_click(self, item):
        entry = item.data(Qt.UserRole)
        exch, sym, display = self._parse(entry)
        self.selected.emit(exch, sym, display)

    def update_entries(self, entries: list):
        self._all = entries
        self._populate(entries)
        count = len(entries)
        self.setTitle(f"{self.title().split('(')[0].strip()}  ({count})")


# ── Main panel ────────────────────────────────────────────────────────────────

class OrderPanel(QWidget):
    order_placed = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._side    = "BUY"
        self._ltp     = 0.0
        self._exchange= "NSE"   # tracks current exchange selection
        self._ltp_timer = QTimer(self)
        self._ltp_timer.setSingleShot(True)
        self._ltp_timer.timeout.connect(self._fetch_ltp)
        self._build_ui()
        # Load live F&O instruments in background
        self._load_instruments()

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(14)

        # ── Left: Order Form ─────────────────────────────────────
        form_box = QGroupBox("Place New Order")
        form_box.setStyleSheet(
            "QGroupBox{color:#AAAACC;font-weight:bold;font-size:13px;"
            "border:1px solid #252538;border-radius:8px;margin-top:10px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;}"
        )
        form_box.setMinimumWidth(340)
        form_box.setMaximumWidth(440)
        form = QFormLayout(form_box)
        form.setSpacing(9)
        form.setContentsMargins(14, 18, 14, 14)

        # Symbol + LTP badge + autocomplete
        sym_row = QWidget()
        sym_lay = QHBoxLayout(sym_row)
        sym_lay.setContentsMargins(0, 0, 0, 0)
        sym_lay.setSpacing(6)
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("e.g. TCS-EQ, NIFTY25JUN26FUT")
        self.symbol_input.textChanged.connect(self._on_symbol_changed)

        # Autocomplete with all equity symbols
        self._sym_model = QStringListModel(EQUITY_STOCKS)
        self._completer = QCompleter(self._sym_model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setMaxVisibleItems(12)
        self.symbol_input.setCompleter(self._completer)
        sym_lay.addWidget(self.symbol_input, 1)

        self.ltp_badge = QLabel("LTP  —")
        self.ltp_badge.setFixedWidth(105)
        self.ltp_badge.setAlignment(Qt.AlignCenter)
        self.ltp_badge.setStyleSheet(
            "color:#666680;font-size:11px;padding:3px 6px;"
            "background:#1C1C2A;border:1px solid #353550;border-radius:4px;"
        )
        sym_lay.addWidget(self.ltp_badge)
        form.addRow("Symbol *", sym_row)

        sym_hint = QLabel("Equity: TCS-EQ  |  F&O: NFO exchange")
        sym_hint.setStyleSheet("color:#555570;font-size:10px;")
        form.addRow("", sym_hint)

        # Exchange — NSE / BSE / NFO / BFO
        self.exchange_combo = QComboBox()
        self.exchange_combo.addItems(["NSE", "BSE", "NFO", "BFO"])
        self.exchange_combo.currentTextChanged.connect(self._on_exchange_changed)
        form.addRow("Exchange", self.exchange_combo)

        # BUY / SELL
        side_w = QWidget()
        side_l = QHBoxLayout(side_w)
        side_l.setContentsMargins(0, 0, 0, 0)
        side_l.setSpacing(6)
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

        self.order_type_combo = QComboBox()
        self.order_type_combo.addItems(["MARKET", "LIMIT", "SL", "SL-M"])
        self.order_type_combo.currentTextChanged.connect(self._update_price_visibility)
        form.addRow("Order Type", self.order_type_combo)

        self.product_combo  = QComboBox(); self.product_combo.addItems(["CNC", "MIS", "NRML"])
        self.variety_combo  = QComboBox(); self.variety_combo.addItems(["regular", "amo"])
        self.validity_combo = QComboBox(); self.validity_combo.addItems(["DAY", "IOC"])
        form.addRow("Product",  self.product_combo)
        form.addRow("Variety",  self.variety_combo)
        form.addRow("Validity", self.validity_combo)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 1_000_000)
        self.qty_spin.setValue(1)
        form.addRow("Quantity *", self.qty_spin)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 1e7); self.price_spin.setDecimals(2)
        self.price_spin.setPrefix("₹ ")
        self._price_lbl = QLabel("Price")
        form.addRow(self._price_lbl, self.price_spin)

        self.trigger_spin = QDoubleSpinBox()
        self.trigger_spin.setRange(0, 1e7); self.trigger_spin.setDecimals(2)
        self.trigger_spin.setPrefix("₹ ")
        self._trigger_lbl = QLabel("Trigger Price")
        form.addRow(self._trigger_lbl, self.trigger_spin)
        self._update_price_visibility("MARKET")

        btn_w = QWidget()
        btn_l = QHBoxLayout(btn_w)
        btn_l.setContentsMargins(0, 0, 0, 0); btn_l.setSpacing(8)
        self.submit_btn = QPushButton("Place Order")
        self.submit_btn.setFixedHeight(40)
        self.submit_btn.setStyleSheet(
            "background:#1A5A30;color:#50DD80;border-color:#2A7040;"
            "font-weight:bold;font-size:13px;")
        self.submit_btn.clicked.connect(self._place_order)
        clear_btn = QPushButton("Clear"); clear_btn.setFixedHeight(40)
        clear_btn.clicked.connect(self._clear_form)
        btn_l.addWidget(self.submit_btn); btn_l.addWidget(clear_btn)
        form.addRow("", btn_w)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True); self.status_lbl.setMinimumHeight(18)
        form.addRow("", self.status_lbl)
        outer.addWidget(form_box, 0)

        # ── Right: Equity (top) + F&O (bottom) — VERTICAL splitter ──
        # Vertical splitter means the two panels stack top/bottom
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(6)
        splitter.setStyleSheet(
            "QSplitter::handle{background:#252538;}"
            "QSplitter::handle:hover{background:#4060C8;}"
        )

        # Equity panel — top half
        eq_entries = [f"NSE|{s}|{s}" for s in EQUITY_STOCKS]
        self._equity_box = StockListBox(
            f"📈  Equity Stocks  ({len(EQUITY_STOCKS)})", eq_entries
        )
        self._equity_box.selected.connect(self._on_stock_selected)
        splitter.addWidget(self._equity_box)

        # F&O panel — bottom half, renamed
        self._fno_box = StockListBox(
            f"📊  F&O  ({len(FNO_SEED)})", FNO_SEED
        )
        self._fno_box.selected.connect(self._on_stock_selected)
        splitter.addWidget(self._fno_box)

        splitter.setSizes([350, 250])
        outer.addWidget(splitter, 1)

    # ── Instrument loader ─────────────────────────────────────────

    def _load_instruments(self):
        self._inst_loader = InstrumentLoader()
        self._inst_loader.fno_ready.connect(self._on_fno_loaded)
        self._inst_loader.start()

    def _on_fno_loaded(self, entries: list):
        self._fno_box.update_entries(entries)
        # Also update autocomplete with F&O symbols
        fno_syms = [e.split("|")[1] for e in entries if "|" in e]
        all_syms = EQUITY_STOCKS + fno_syms
        self._sym_model.setStringList(all_syms)

    # ── Stock selection ───────────────────────────────────────────

    def _on_stock_selected(self, exchange: str, symbol: str, display: str):
        """Fill symbol and set correct exchange when user clicks a stock."""
        self.symbol_input.setText(symbol)
        # Set exchange dropdown to match
        idx = self.exchange_combo.findText(exchange)
        if idx >= 0:
            self.exchange_combo.setCurrentIndex(idx)
        # Switch product to NRML for F&O
        if exchange in ("NFO", "BFO"):
            self.product_combo.setCurrentText("NRML")
        else:
            self.product_combo.setCurrentText("CNC")
        self.symbol_input.setFocus()

    # ── Exchange changed ──────────────────────────────────────────

    def _on_exchange_changed(self, exchange: str):
        self._exchange = exchange
        self._on_symbol_changed()

    # ── LTP auto-fetch ────────────────────────────────────────────

    def _on_symbol_changed(self):
        self._ltp_timer.start(800)
        self.ltp_badge.setText("LTP  …")
        self.ltp_badge.setStyleSheet(
            "color:#888899;font-size:11px;padding:3px 6px;"
            "background:#1C1C2A;border:1px solid #353550;border-radius:4px;"
        )

    def _fetch_ltp(self):
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            self._reset_ltp_badge(); return
        exchange = self.exchange_combo.currentText()
        self._ltp_worker = LTPWorker(exchange, symbol)
        self._ltp_worker.done.connect(self._on_ltp)
        self._ltp_worker.error.connect(self._on_ltp_error)
        self._ltp_worker.start()

    def _on_ltp(self, ltp: float):
        self._ltp = ltp
        self.ltp_badge.setText(f"₹ {ltp:,.2f}")
        self.ltp_badge.setStyleSheet(
            "color:#40CC70;font-size:11px;font-weight:bold;padding:3px 6px;"
            "background:#0F2A1A;border:1px solid #1A5A30;border-radius:4px;"
        )
        ot = self.order_type_combo.currentText()
        if ot in ("LIMIT", "SL") and self.price_spin.value() == 0:
            self.price_spin.setValue(ltp)
        if ot in ("SL", "SL-M") and self.trigger_spin.value() == 0:
            self.trigger_spin.setValue(ltp)

    def _on_ltp_error(self, err: str):
        self._ltp = 0.0
        self.ltp_badge.setText("LTP  N/A")
        self.ltp_badge.setStyleSheet(
            "color:#FF8800;font-size:11px;padding:3px 6px;"
            "background:#2A1A00;border:1px solid #5A3A00;border-radius:4px;"
        )

    def _reset_ltp_badge(self):
        self._ltp = 0.0
        self.ltp_badge.setText("LTP  —")
        self.ltp_badge.setStyleSheet(
            "color:#666680;font-size:11px;padding:3px 6px;"
            "background:#1C1C2A;border:1px solid #353550;border-radius:4px;"
        )

    # ── Price visibility ──────────────────────────────────────────

    def _update_price_visibility(self, ot: str):
        need_p = ot in ("LIMIT", "SL")
        need_t = ot in ("SL", "SL-M")
        self.price_spin.setEnabled(need_p)
        self.trigger_spin.setEnabled(need_t)
        self._price_lbl.setStyleSheet("color:#AAAACC;" if need_p else "color:#555570;")
        self._trigger_lbl.setStyleSheet("color:#AAAACC;" if need_t else "color:#555570;")
        if need_p and self.price_spin.value() == 0 and self._ltp:
            self.price_spin.setValue(self._ltp)
        if need_t and self.trigger_spin.value() == 0 and self._ltp:
            self.trigger_spin.setValue(self._ltp)

    def _set_side(self, side: str):
        self._side = side
        self.buy_btn.setChecked(side == "BUY")
        self.sell_btn.setChecked(side == "SELL")
        self.buy_btn.setStyleSheet(
            "background:#1A5A30;color:#50DD80;border-color:#2A7040;font-weight:bold;"
            if side == "BUY" else "")
        self.sell_btn.setStyleSheet(
            "background:#5A1A1A;color:#FF6060;border-color:#703030;font-weight:bold;"
            if side == "SELL" else "")

    # ── Place order ───────────────────────────────────────────────

    def _place_order(self):
        symbol = self.symbol_input.text().strip().upper()
        if not symbol:
            self._set_status("Symbol is required", error=True); return

        ot = self.order_type_combo.currentText()
        if ot == "MARKET":
            price, trigger_price = "0", "0"
        elif ot == "LIMIT":
            price, trigger_price = f"{self.price_spin.value():.2f}", "0"
        elif ot == "SL":
            price         = f"{self.price_spin.value():.2f}"
            trigger_price = f"{self.trigger_spin.value():.2f}"
        else:
            price, trigger_price = "0", f"{self.trigger_spin.value():.2f}"

        kwargs = dict(
            variety=self.variety_combo.currentText(), symbol=symbol,
            exchange=self.exchange_combo.currentText(),
            transaction_type=self._side, order_type=ot,
            quantity=str(self.qty_spin.value()),
            product=self.product_combo.currentText(),
            validity=self.validity_combo.currentText(),
            price=price, trigger_price=trigger_price,
            disclosed_quantity="0", tag="",
        )
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("Placing…")
        self._set_status("")
        self._order_worker = PlaceOrderWorker(kwargs)
        self._order_worker.success.connect(self._on_order_ok)
        self._order_worker.failure.connect(self._on_order_fail)
        self._order_worker.start()

    def _on_order_ok(self, result: dict):
        sym = self.symbol_input.text().strip().upper()
        self.submit_btn.setEnabled(True); self.submit_btn.setText("Place Order")
        self._set_status(f"✓  Order placed for {sym}", error=False)
        self.order_placed.emit(result)

    def _on_order_fail(self, error: str):
        self.submit_btn.setEnabled(True); self.submit_btn.setText("Place Order")
        hint = ""
        if "scrip" in error.lower() or "symbol" in error.lower() or "invalid" in error.lower():
            sym  = self.symbol_input.text().strip().upper()
            exch = self.exchange_combo.currentText()
            if exch in ("NSE", "BSE") and not sym.endswith("-EQ"):
                hint = f"  Tip: equity needs '{sym}-EQ'"
            elif exch in ("NFO", "BFO") and not any(
                    x in sym for x in ("FUT", "CE", "PE")):
                hint = "  Tip: F&O symbol needs expiry+type, e.g. NIFTY25JUN26FUT"
        self._set_status(f"✗  {error}{hint}", error=True)
        self.order_placed.emit({"success": False, "error": error})

    def _set_status(self, msg: str, error: bool = True):
        color = "#FF6060" if error else "#50DD80"
        self.status_lbl.setText(f'<span style="color:{color};font-size:12px;">{msg}</span>')

    def _clear_form(self):
        self.symbol_input.clear()
        self.qty_spin.setValue(1)
        self.price_spin.setValue(0); self.trigger_spin.setValue(0)
        self._reset_ltp_badge(); self.status_lbl.setText("")
        self._set_side("BUY"); self.order_type_combo.setCurrentIndex(0)
