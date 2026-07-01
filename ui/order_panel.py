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
    QSpinBox, QGroupBox, QFormLayout, QListWidget, QListView,
    QCompleter, QSplitter, QFrame, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QTimer, QStringListModel, QAbstractListModel, QModelIndex
from PyQt5.QtGui import QColor
from core.api_client import APIClient

# ── Static equity seed — symbol → display name ───────────────────────────────
# Used only before the instrument API loads. Replaced by live data on startup.
# Format: { "SYMBOL-EQ": "Company Name" }
EQUITY_SEED = {
    "ADANIPORTS-EQ": "Adani Ports & SEZ",
    "APOLLOHOSP-EQ": "Apollo Hospitals",
    "ASIANPAINT-EQ": "Asian Paints",
    "AXISBANK-EQ":   "Axis Bank",
    "BAJAJ-AUTO-EQ": "Bajaj Auto",
    "BAJAJFINSV-EQ": "Bajaj Finserv",
    "BAJFINANCE-EQ": "Bajaj Finance",
    "BERGEPAINT-EQ": "Berger Paints",
    "BHARTIARTL-EQ": "Bharti Airtel",
    "BPCL-EQ":       "Bharat Petroleum",
    "BRITANNIA-EQ":  "Britannia Industries",
    "CIPLA-EQ":      "Cipla",
    "COALINDIA-EQ":  "Coal India",
    "COLPAL-EQ":     "Colgate-Palmolive India",
    "DABUR-EQ":      "Dabur India",
    "DIVISLAB-EQ":   "Divi's Laboratories",
    "DMART-EQ":      "Avenue Supermarts (DMart)",
    "DRREDDY-EQ":    "Dr. Reddy's Laboratories",
    "EICHERMOT-EQ":  "Eicher Motors",
    "GRASIM-EQ":     "Grasim Industries",
    "HAVELLS-EQ":    "Havells India",
    "HCLTECH-EQ":    "HCL Technologies",
    "HDFCBANK-EQ":   "HDFC Bank",
    "HDFCLIFE-EQ":   "HDFC Life Insurance",
    "HEROMOTOCO-EQ": "Hero MotoCorp",
    "HINDALCO-EQ":   "Hindalco Industries",
    "HINDUNILVR-EQ": "Hindustan Unilever",
    "ICICIBANK-EQ":  "ICICI Bank",
    "IDEA-EQ":       "Vodafone Idea",
    "INDUSINDBK-EQ": "IndusInd Bank",
    "INFY-EQ":       "Infosys",
    "IOC-EQ":        "Indian Oil Corporation",
    "IRCTC-EQ":      "IRCTC",
    "ITC-EQ":        "ITC Limited",
    "JSWSTEEL-EQ":   "JSW Steel",
    "KOTAKBANK-EQ":  "Kotak Mahindra Bank",
    "LT-EQ":         "Larsen & Toubro",
    "MARICO-EQ":     "Marico",
    "MARUTI-EQ":     "Maruti Suzuki",
    "NESTLEIND-EQ":  "Nestle India",
    "NTPC-EQ":       "NTPC",
    "NYKAA-EQ":      "Nykaa (FSN E-Commerce)",
    "ONGC-EQ":       "Oil & Natural Gas Corp",
    "PAYTM-EQ":      "Paytm (One 97 Communications)",
    "PIDILITIND-EQ": "Pidilite Industries",
    "POWERGRID-EQ":  "Power Grid Corporation",
    "RELIANCE-EQ":   "Reliance Industries",
    "SBIN-EQ":       "State Bank of India",
    "SBILIFE-EQ":    "SBI Life Insurance",
    "SUNPHARMA-EQ":  "Sun Pharmaceutical",
    "TATAMOTORS-EQ": "Tata Motors",
    "TATASTEEL-EQ":  "Tata Steel",
    "TATACONSUM-EQ": "Tata Consumer Products",
    "TCS-EQ":        "Tata Consultancy Services",
    "TECHM-EQ":      "Tech Mahindra",
    "TITAN-EQ":      "Titan Company",
    "ULTRACEMCO-EQ": "UltraTech Cement",
    "WIPRO-EQ":      "Wipro",
    "YESBANK-EQ":    "Yes Bank",
    "ZOMATO-EQ":     "Zomato",
}

# Keep a flat list of symbols for autocomplete seeding
EQUITY_STOCKS = list(EQUITY_SEED.keys())

def _seed_entry(sym: str) -> str:
    """Build a pipe entry with proper display name for the seed list."""
    name = EQUITY_SEED.get(sym, sym.replace("-EQ", ""))
    return f"NSE|{sym}|{name}  ({sym})"

def _cache_dir() -> str:
    """Returns the cache/ directory next to the project root / EXE."""
    import os, sys
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
    else:
        # This file lives in ui/ — go up one level to project root
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(app_dir, "cache")
    os.makedirs(d, exist_ok=True)
    return d


# Static F&O seed — shown before the API loads
# Display format: "Company Name — MonthYY FUT"
FNO_SEED = [
    "NFO|NIFTY25JUN26FUT|Nifty 50 — Jun 26 FUT",
    "NFO|BANKNIFTY25JUN26FUT|Bank Nifty — Jun 26 FUT",
    "NFO|FINNIFTY25JUN26FUT|Nifty Financial Svcs — Jun 26 FUT",
    "NFO|RELIANCE25JUN26FUT|Reliance Industries — Jun 26 FUT",
    "NFO|TCS25JUN26FUT|Tata Consultancy Services — Jun 26 FUT",
    "NFO|INFY25JUN26FUT|Infosys — Jun 26 FUT",
    "NFO|HDFCBANK25JUN26FUT|HDFC Bank — Jun 26 FUT",
    "NFO|SBIN25JUN26FUT|State Bank of India — Jun 26 FUT",
    "NFO|ICICIBANK25JUN26FUT|ICICI Bank — Jun 26 FUT",
    "NFO|WIPRO25JUN26FUT|Wipro — Jun 26 FUT",
    "NFO|AXISBANK25JUN26FUT|Axis Bank — Jun 26 FUT",
    "NFO|BAJFINANCE25JUN26FUT|Bajaj Finance — Jun 26 FUT",
    "NFO|TATAMOTORS25JUN26FUT|Tata Motors — Jun 26 FUT",
    "NFO|MARUTI25JUN26FUT|Maruti Suzuki — Jun 26 FUT",
    "NFO|LT25JUN26FUT|Larsen & Toubro — Jun 26 FUT",
]


# ── Instrument master loader ──────────────────────────────────────────────────

class InstrumentLoader(QThread):
    """
    Loads the full instrument CSV from:
      GET https://api.mstock.trade/instruments/scriptmaster
    Parses and emits:
      equity_ready — list of "NSE|SYMBOL-EQ|SYMBOL-EQ" strings
      fno_ready    — list of "NFO|NIFTY25JUN26FUT|display" strings
    Falls back to static lists if API fails.
    """
    fno_ready    = pyqtSignal(list)
    equity_ready = pyqtSignal(list)

    # ── Cache helpers ─────────────────────────────────────────────
    @staticmethod
    def _cache_path():
        """Daily cache file in the cache/ directory."""
        from datetime import date
        return f"{_cache_dir()}/instruments_{date.today():%Y%m%d}.json"

    @staticmethod
    def _load_cache(path: str):
        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("equity", []), data.get("fno", [])
        except Exception:
            return [], []

    @staticmethod
    def _save_cache(path: str, equity: list, fno: list):
        import json, os
        # Remove yesterday's cache files from the cache/ directory
        d = _cache_dir()
        for fn in os.listdir(d):
            if fn.startswith("instruments_") and fn.endswith(".json") and fn != os.path.basename(path):
                try:
                    os.remove(os.path.join(d, fn))
                except Exception:
                    pass
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"equity": equity, "fno": fno}, f)
        except Exception:
            pass

    def run(self):
        import logging, requests as _req
        log = logging.getLogger(__name__)

        # ── Try cache first (refreshed once per day) ──────────────
        cache = self._cache_path()
        eq_cached, fno_cached = self._load_cache(cache)
        if eq_cached and fno_cached:
            log.info("InstrumentLoader: loaded from cache — %d equity, %d F&O",
                     len(eq_cached), len(fno_cached))
            self.equity_ready.emit(eq_cached)
            self.fno_ready.emit(fno_cached)
            return

        # ── Fetch from API ────────────────────────────────────────
        try:
            client = APIClient.get()
            url = "https://api.mstock.trade/openapi/typea/instruments/scriptmaster"
            log.info("InstrumentLoader: fetching %s", url)
            resp = _req.get(url, headers=client._auth_headers(), timeout=30)
            log.info("InstrumentLoader: HTTP %s", resp.status_code)
            resp.raise_for_status()
            csv_text = resp.text
            total_lines = len(csv_text.strip().splitlines())
            log.info("Scriptmaster: %d raw lines", total_lines)

            equity, fno = self._parse(csv_text, log)
            log.info("Parsed: %d equity, %d F&O instruments", len(equity), len(fno))

            if equity and fno:
                self._save_cache(cache, equity, fno)
                log.info("InstrumentLoader: saved to cache %s", cache)

            self.equity_ready.emit(equity if equity else
                                   [_seed_entry(s) for s in EQUITY_STOCKS])
            self.fno_ready.emit(fno if fno else FNO_SEED)

        except Exception as e:
            log.warning("InstrumentLoader failed (%s) — using static lists", e)
            self.equity_ready.emit([_seed_entry(s) for s in EQUITY_STOCKS])
            self.fno_ready.emit(FNO_SEED)

    def _parse(self, csv_text: str, log) -> tuple:
        """
        Returns (equity_entries, fno_entries).
        Both are lists of "EXCHANGE|SYMBOL|DISPLAY" strings.

        mStock scriptmaster CSV columns (typical):
          instrument_token, exchange_token, tradingsymbol, name,
          last_price, expiry, strike, tick_size, lot_size,
          instrument_type, segment, exchange
        """
        lines = csv_text.strip().splitlines()
        if len(lines) < 2:
            log.warning("scriptmaster CSV has < 2 lines, cannot parse")
            return [], []

        try:
            header = [h.strip().strip('"').lower() for h in lines[0].split(",")]
            log.info("scriptmaster columns: %s", header)
            sym_idx  = header.index("tradingsymbol")
            exch_idx = header.index("exchange")
            type_idx = header.index("instrument_type")
            name_idx = header.index("name") if "name" in header else -1
            exp_idx  = header.index("expiry") if "expiry" in header else -1
        except (ValueError, IndexError) as e:
            log.warning("Cannot find required columns in scriptmaster: %s", e)
            return [], []

        equity, fno = [], []
        skipped = 0

        for line in lines[1:]:
            parts = line.split(",")
            needed = max(sym_idx, exch_idx, type_idx) + 1
            if len(parts) < needed:
                skipped += 1
                continue

            exch  = parts[exch_idx].strip().strip('"')
            sym   = parts[sym_idx].strip().strip('"')
            itype = parts[type_idx].strip().strip('"').upper()

            if not sym or not exch:
                continue

            # Equity — NSE/BSE EQ instruments
            # Filter out test/invalid symbols:
            #   - Contain digits at start (011NSETEST, 021NSETEST etc)
            #   - Contain "TEST" or "DUMMY"
            #   - Shorter than 2 chars
            if exch in ("NSE", "BSE") and itype == "EQ":
                if (len(sym) < 2 or
                        sym[:1].isdigit() or
                        "TEST" in sym.upper() or
                        "DUMMY" in sym.upper()):
                    continue
                # Ensure -EQ suffix for NSE/BSE equity
                if not sym.upper().endswith("-EQ"):
                    sym = sym + "-EQ"
                display = sym
                equity.append(f"{exch}|{sym}|{display}")

            # F&O — NFO/BFO futures and options
            elif exch in ("NFO", "BFO") and itype in ("FUT", "CE", "PE"):
                expiry = parts[exp_idx].strip().strip('"') if exp_idx >= 0 and exp_idx < len(parts) else ""
                display = f"{sym}  {expiry}".strip() if expiry else sym
                fno.append(f"{exch}|{sym}|{display}")

        if skipped:
            log.info("scriptmaster: skipped %d malformed lines", skipped)

        # Deduplicate equity (same symbol may appear on NSE and BSE)
        seen = set()
        eq_deduped = []
        for e in sorted(equity):
            sym = e.split("|")[1]
            if sym not in seen:
                seen.add(sym)
                eq_deduped.append(e)

        # Sort F&O: FUT first, then CE/PE; alphabetical within each
        fut = sorted([r for r in fno if r.split("|")[1].endswith("FUT")])
        opt = sorted([r for r in fno if not r.split("|")[1].endswith("FUT")])
        return eq_deduped, fut + opt


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

class _VirtualModel(QAbstractListModel):
    """
    Virtual list model — holds all entries in a plain Python list.
    Qt only asks for display data for visible rows, so 149k entries
    cost almost nothing until the user scrolls or searches.
    """
    def __init__(self, entries=None):
        super().__init__()
        self._entries: list = entries or []

    def rowCount(self, parent=QModelIndex()):
        return len(self._entries)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._entries):
            return None
        entry = self._entries[index.row()]
        if role == Qt.DisplayRole:
            parts = entry.split("|")
            return parts[2] if len(parts) == 3 else entry
        if role == Qt.UserRole:
            return entry
        return None

    def set_entries(self, entries: list):
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()

    def entry_at(self, row: int) -> str:
        return self._entries[row] if 0 <= row < len(self._entries) else ""


class StockListBox(QGroupBox):
    """
    Searchable stock list using a virtual QAbstractListModel + QListView.
    Only visible rows are rendered — handles 150k entries without lag.
    Debounces search input so filtering doesn't block the UI.
    """
    selected = pyqtSignal(str, str, str)   # exchange, symbol, display

    _STYLE = (
        "QGroupBox{color:#AAAACC;font-weight:bold;font-size:16px;"
        "border:1px solid #252538;border-radius:6px;margin-top:8px;}"
        "QGroupBox::title{subcontrol-origin:margin;left:8px;}"
        "QListView{background:#0E0E18;border:1px solid #252538;"
        "color:#DCDCE6;font-size:16px;outline:none;}"
        "QListView::item{padding:4px 8px;border-bottom:1px solid #1A1A28;}"
        "QListView::item:hover{background:#1C1C2A;color:#FFF;}"
        "QListView::item:selected{background:#252545;color:#FFF;}"
        "QLineEdit{background:#1C1C2A;border:1px solid #353550;"
        "border-radius:3px;padding:4px 8px;color:#DCDCE6;font-size:16px;}"
        "QLineEdit:focus{border-color:#5078DC;}"
    )

    def __init__(self, title: str, entries: list, parent=None):
        super().__init__(title, parent)
        self._all: list = entries
        self.setStyleSheet(self._STYLE)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 14, 6, 6)
        lay.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.textChanged.connect(self._on_search_changed)
        lay.addWidget(self._search)

        # Debounce timer — filter fires 200ms after typing stops
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.timeout.connect(self._apply_filter)
        self._pending_query = ""

        self._model = _VirtualModel(entries)
        self._view  = QListView()
        self._view.setModel(self._model)
        self._view.setUniformItemSizes(True)        # critical for speed
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.clicked.connect(self._on_click)
        lay.addWidget(self._view)

    def _on_search_changed(self, text: str):
        self._pending_query = text.strip().upper()
        self._filter_timer.start(200)

    def _apply_filter(self):
        q = self._pending_query
        if not q:
            self._model.set_entries(self._all)
        else:
            self._model.set_entries([e for e in self._all if q in e.upper()])

    @staticmethod
    def _parse(entry: str):
        parts = entry.split("|")
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        return "NSE", entry, entry

    def _on_click(self, index):
        entry = self._model.entry_at(index.row())
        if entry:
            exch, sym, display = self._parse(entry)
            self.selected.emit(exch, sym, display)

    def update_entries(self, entries: list):
        self._all = entries
        self._model.set_entries(entries)
        title_base = self.title().split("(")[0].strip()
        self.setTitle(f"{title_base}  ({len(entries)})")


class FnoListBox(StockListBox):
    """
    F&O variant of StockListBox.
    - Shows futures only by default (~3k rows — fast)
    - When user types a search query, also searches options (loaded lazily)
    - Options (~146k) are read from the daily cache file on first search
    """

    def __init__(self, title: str, seed: list, parent=None):
        super().__init__(title, seed, parent)
        self._futures: list = seed
        self._options: list = []          # loaded lazily
        self._options_loaded = False
        self._hint = QLabel("Showing futures — type to search all options")
        self._hint.setStyleSheet(
            "color:#555570;font-size:16px;padding:2px 6px;"
        )
        # Insert hint above the list view
        lay = self.layout()
        lay.insertWidget(1, self._hint)   # after search box

    def set_futures(self, futures: list):
        self._futures = futures
        self._all = futures
        self._model.set_entries(futures)
        base = self.title().split("(")[0].strip()
        self.setTitle(f"{base}  ({len(futures)} futures)")

    def _load_options_if_needed(self):
        if self._options_loaded:
            return
        import json, os
        from datetime import date
        opt_file = os.path.join(_cache_dir(), f"opt_{date.today():%Y%m%d}.json")
        if os.path.exists(opt_file):
            try:
                with open(opt_file, "r", encoding="utf-8") as f:
                    self._options = json.load(f)
                self._options_loaded = True
            except Exception:
                self._options_loaded = True   # don't retry on error

    def _apply_filter(self):
        q = self._pending_query
        if not q:
            # No query — show futures only
            self._model.set_entries(self._futures)
            self._hint.setText(
                f"Showing {len(self._futures):,} futures — type to search all options"
            )
        else:
            # Load options lazily on first search
            self._load_options_if_needed()
            combined = self._futures + self._options
            results = [e for e in combined if q in e.upper()]
            self._model.set_entries(results)
            self._hint.setText(
                f"{len(results):,} results  "
                f"(from {len(combined):,} total instruments)"
            )


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
        """
        Layout (matches sketch):
        ┌─────────────────────┬──────────────────────────┐
        │                     │  📈 Equity List           │
        │  Place New Order    ├──────────────────────────┤
        │  (form)             │  📊 F&O List              │
        │                     ├──────────────────────────┤
        │                     │  ℹ Quick Reference        │
        └─────────────────────┴──────────────────────────┘
        Left column  = order form  (fixed ~400px)
        Right column = vertical splitter with 3 equal panels
        """
        root = QSplitter(Qt.Horizontal)
        root.setHandleWidth(5)
        root.setStyleSheet(
            "QSplitter::handle{background:#252538;}"
            "QSplitter::handle:hover{background:#4060C8;}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(root)

        # ── LEFT: Order Form ──────────────────────────────────────
        form_box = QGroupBox("Place New Order")
        form_box.setStyleSheet(
            "QGroupBox{color:#AAAACC;font-weight:bold;font-size:16px;"
            "border:1px solid #252538;border-radius:8px;margin-top:10px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;}"
        )
        form = QFormLayout(form_box)
        form.setSpacing(9)
        form.setContentsMargins(14, 18, 14, 14)

        # Symbol + LTP
        sym_row = QWidget()
        sym_lay = QHBoxLayout(sym_row)
        sym_lay.setContentsMargins(0,0,0,0); sym_lay.setSpacing(6)
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("e.g. TCS-EQ, NIFTY25JUN26FUT")
        self.symbol_input.textChanged.connect(self._on_symbol_changed)
        # Autocomplete seeded with futures symbols — equity removed
        _fut_syms = [e.split("|")[1] for e in FNO_SEED if "|" in e]
        self._sym_model = QStringListModel(_fut_syms)
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
            "color:#666680;font-size:16px;padding:3px 6px;"
            "background:#1C1C2A;border:1px solid #353550;border-radius:4px;")
        sym_lay.addWidget(self.ltp_badge)
        form.addRow("Symbol *", sym_row)
        hint = QLabel("Equity: TCS-EQ  |  F&O: NFO exchange")
        hint.setStyleSheet("color:#555570;font-size:16px;")
        form.addRow("", hint)

        # Exchange
        self.exchange_combo = QComboBox()
        self.exchange_combo.addItems(["NFO","NSE","BSE","BFO"])
        self.exchange_combo.currentTextChanged.connect(self._on_exchange_changed)
        form.addRow("Exchange", self.exchange_combo)

        # BUY / SELL
        side_w = QWidget()
        side_l = QHBoxLayout(side_w)
        side_l.setContentsMargins(0,0,0,0); side_l.setSpacing(6)
        self.buy_btn  = QPushButton("BUY");  self.buy_btn.setCheckable(True)
        self.sell_btn = QPushButton("SELL"); self.sell_btn.setCheckable(True)
        self.buy_btn.clicked.connect(lambda: self._set_side("BUY"))
        self.sell_btn.clicked.connect(lambda: self._set_side("SELL"))
        side_l.addWidget(self.buy_btn); side_l.addWidget(self.sell_btn)
        form.addRow("Side", side_w)
        self._set_side("BUY")

        # Order type / Product / Variety / Validity
        self.order_type_combo = QComboBox()
        self.order_type_combo.addItems(["MARKET","LIMIT","SL","SL-M"])
        self.order_type_combo.currentTextChanged.connect(self._update_price_visibility)
        form.addRow("Order Type", self.order_type_combo)
        self.product_combo  = QComboBox(); self.product_combo.addItems(["CNC","MIS","NRML"])
        self.variety_combo  = QComboBox(); self.variety_combo.addItems(["regular","amo"])
        self.validity_combo = QComboBox(); self.validity_combo.addItems(["DAY","IOC"])
        form.addRow("Product",  self.product_combo)
        form.addRow("Variety",  self.variety_combo)
        form.addRow("Validity", self.validity_combo)

        # Qty / Price / Trigger
        self.qty_spin = QSpinBox(); self.qty_spin.setRange(1,1_000_000); self.qty_spin.setValue(1)
        form.addRow("Quantity *", self.qty_spin)
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0,1e7); self.price_spin.setDecimals(2); self.price_spin.setPrefix("₹ ")
        self._price_lbl = QLabel("Price")
        form.addRow(self._price_lbl, self.price_spin)
        self.trigger_spin = QDoubleSpinBox()
        self.trigger_spin.setRange(0,1e7); self.trigger_spin.setDecimals(2); self.trigger_spin.setPrefix("₹ ")
        self._trigger_lbl = QLabel("Trigger Price")
        form.addRow(self._trigger_lbl, self.trigger_spin)
        self._update_price_visibility("MARKET")

        # Buttons
        btn_w = QWidget(); btn_l = QHBoxLayout(btn_w)
        btn_l.setContentsMargins(0,0,0,0); btn_l.setSpacing(8)
        self.submit_btn = QPushButton("Place Order")
        self.submit_btn.setFixedHeight(40)
        self.submit_btn.setStyleSheet(
            "background:#1A5A30;color:#50DD80;border-color:#2A7040;font-weight:bold;font-size:16px;")
        self.submit_btn.clicked.connect(self._place_order)
        clear_btn = QPushButton("Clear"); clear_btn.setFixedHeight(40)
        clear_btn.clicked.connect(self._clear_form)
        btn_l.addWidget(self.submit_btn); btn_l.addWidget(clear_btn)
        form.addRow("", btn_w)
        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True); self.status_lbl.setMinimumHeight(18)
        form.addRow("", self.status_lbl)

        root.addWidget(form_box)   # col 1: order form

        # ── COL 2: Quick Reference sidebar (always expanded) ──────
        qr_box = QGroupBox("ℹ  Quick Reference")
        qr_box.setStyleSheet(
            "QGroupBox{color:#5090CC;font-weight:bold;font-size:16px;"
            "border:1px solid #252538;border-radius:8px;margin-top:10px;background:#0A0A14;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;}"
        )
        qr_lay = QVBoxLayout(qr_box)
        qr_lay.setContentsMargins(12, 18, 12, 12)
        qr_lbl = QLabel(
            "<style>body{color:#AAAACC;font-size:16px;line-height:1.9;}"
            "b{color:#FFF;font-size:16px;}"
            ".h{color:#5090CC;font-weight:bold;font-size:16px;"
            "display:block;margin-top:12px;margin-bottom:4px;"
            "border-bottom:1px solid #252538;padding-bottom:3px;}"
            "</style>"
            "<p class='h'>Symbol Format</p>"
            "<b>NSE/BSE equity:</b> TCS-EQ, INFY-EQ<br>"
            "<b>F&amp;O Future:</b> NIFTY25JUN26FUT<br>"
            "<b>F&amp;O Option:</b> NIFTY25JUN2624000CE<br>"
            "<p class='h'>Order Types</p>"
            "<b>MARKET</b> — best price now<br>"
            "<b>LIMIT</b> — your price or better<br>"
            "<b>SL</b> — stop-loss + limit price<br>"
            "<b>SL-M</b> — stop-loss at market<br>"
            "<p class='h'>Product</p>"
            "<b>CNC</b> — delivery (hold overnight)<br>"
            "<b>MIS</b> — intraday, auto square-off<br>"
            "<b>NRML</b> — F&amp;O overnight<br>"
            "<p class='h'>Validity</p>"
            "<b>DAY</b> — valid today only<br>"
            "<b>IOC</b> — immediate or cancel<br>"
            "<b>AMO</b> — after market order"
        )
        qr_lbl.setTextFormat(Qt.RichText)
        qr_lbl.setWordWrap(True)
        qr_lbl.setAlignment(Qt.AlignTop)
        qr_lbl.setStyleSheet("background:transparent;")
        qr_lay.addWidget(qr_lbl)
        qr_lay.addStretch()
        root.addWidget(qr_box)

        # Two columns: form | quick ref
        root.setSizes([560, 320])

    # ── Instrument loader ─────────────────────────────────────────

    def _load_instruments(self):
        self._inst_loader = InstrumentLoader()
        self._inst_loader.fno_ready.connect(self._on_fno_loaded)
        self._inst_loader.equity_ready.connect(self._on_equity_loaded)
        self._inst_loader.start()

    def _on_fno_loaded(self, entries: list):
        """Update autocomplete with live futures symbols — no list box."""
        fut_syms = [e.split("|")[1] for e in entries if "|" in e]
        all_syms = list(self._sym_model.stringList()) + fut_syms
        self._sym_model.setStringList(sorted(set(all_syms)))

    def _on_equity_loaded(self, entries: list):
        """Equity removed — no-op."""
        pass

    # ── Stock selection ───────────────────────────────────────────

    def _on_stock_selected(self, exchange: str, symbol: str, display: str):
        """Fill symbol and set correct exchange when user clicks a stock."""
        # Auto-append -EQ for NSE/BSE equity if not already present
        if exchange in ("NSE", "BSE") and not symbol.upper().endswith("-EQ"):
            symbol = symbol + "-EQ"
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
            "color:#888899;font-size:16px;padding:3px 6px;"
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
            "color:#40CC70;font-size:16px;font-weight:bold;padding:3px 6px;"
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
            "color:#FF8800;font-size:16px;padding:3px 6px;"
            "background:#2A1A00;border:1px solid #5A3A00;border-radius:4px;"
        )

    def _reset_ltp_badge(self):
        self._ltp = 0.0
        self.ltp_badge.setText("LTP  —")
        self.ltp_badge.setStyleSheet(
            "color:#666680;font-size:16px;padding:3px 6px;"
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
        self.status_lbl.setText(f'<span style="color:{color};font-size:16px;">{msg}</span>')

    def _clear_form(self):
        self.symbol_input.clear()
        self.qty_spin.setValue(1)
        self.price_spin.setValue(0); self.trigger_spin.setValue(0)
        self._reset_ltp_badge(); self.status_lbl.setText("")
        self._set_side("BUY"); self.order_type_combo.setCurrentIndex(0)
