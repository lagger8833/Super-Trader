"""
ui/main_window.py
The main application window after authentication.
Tabs: Holdings | Orders | Algo Engine | Place Order
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter,
    QStatusBar, QFrame, QMessageBox, QApplication,
    QGroupBox, QScrollArea, QFormLayout
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QColor, QFont, QBrush

from core.api_client import APIClient
from core.auth_manager import clear_credentials

STYLE = """
QMainWindow, QWidget { background-color: #12121C; color: #DCDCE6; }
QTabWidget::pane {
    border: 1px solid #252538; border-top: none;
    background-color: #15151F;
}
QTabBar::tab {
    background-color: #1C1C2A; color: #888899;
    padding: 10px 20px; border: 1px solid #252538;
    border-bottom: none; margin-right: 2px;
    font-size: 12px; font-weight: bold;
}
QTabBar::tab:selected { background-color: #15151F; color: #FFFFFF; border-bottom: 2px solid #4060C8; }
QTabBar::tab:hover { color: #CCCCDD; }

QTableWidget {
    background-color: #15151F; gridline-color: #252538;
    color: #DCDCE6; border: none; font-size: 12px;
}
QTableWidget::item { padding: 6px 10px; border-bottom: 1px solid #252538; }
QTableWidget::item:selected { background-color: #252545; color: #FFFFFF; }
QHeaderView::section {
    background-color: #1C1C2A; color: #AAAACC;
    padding: 8px 10px; border: none; border-bottom: 1px solid #353550;
    font-size: 11px; font-weight: bold; text-transform: uppercase;
}

QPushButton {
    background-color: #252538; color: #DCDCE6; border: 1px solid #353550;
    border-radius: 4px; padding: 6px 14px; font-size: 12px;
}
QPushButton:hover { background-color: #303048; }
QPushButton.buy_btn { background-color: #1A5A30; color: #50DD80; border-color: #2A7040; }
QPushButton.buy_btn:hover { background-color: #207040; }
QPushButton.sell_btn { background-color: #5A1A1A; color: #FF6060; border-color: #703030; }
QPushButton.sell_btn:hover { background-color: #703030; }
QPushButton.algo_btn { background-color: #1A3A5A; color: #50A0FF; border-color: #2A5070; }
QPushButton.algo_btn:hover { background-color: #204A70; }

QLabel.section_header {
    color: #AAAACC; font-size: 11px; font-weight: bold;
    padding: 4px 0; border-bottom: 1px solid #252538;
    text-transform: uppercase; letter-spacing: 1px;
}
QLabel.metric_value { color: #FFFFFF; font-size: 16px; font-weight: bold; }
QLabel.metric_label { color: #666680; font-size: 11px; }
QLabel.positive { color: #40CC70; }
QLabel.negative { color: #FF5555; }

QStatusBar { background-color: #0E0E18; color: #555570; font-size: 11px; }

QFrame.metric_card {
    background-color: #1C1C2A; border: 1px solid #252538;
    border-radius: 6px; padding: 12px;
}
"""


class DataWorker(QThread):
    holdings_ready = pyqtSignal(list)
    orders_ready   = pyqtSignal(list)
    funds_ready    = pyqtSignal(dict)
    error          = pyqtSignal(str)

    def __init__(self, what="all"):
        super().__init__()
        self.what = what

    def run(self):
        client = APIClient.get()
        try:
            if self.what in ("all", "holdings"):
                r = client.get_holdings()
                holdings = self._extract_list(r, "data")
                self.holdings_ready.emit(holdings)

            if self.what in ("all", "orders"):
                r = client.get_order_book()
                orders = self._extract_list(r, "data")
                self.orders_ready.emit(orders)

            if self.what in ("all", "funds"):
                r = client.get_fund_summary()
                import logging as _log
                _log.getLogger(__name__).info(
                    "get_fund_summary() raw: %s", str(r)[:600]
                )
                if not r.get("success"):
                    self.error.emit(
                        f"Fund summary failed: {r.get('error', 'unknown')}"
                    )
                else:
                    self.funds_ready.emit(r)
        except Exception as e:
            self.error.emit(str(e))

    def _extract_list(self, result: dict, key: str) -> list:
        data = result.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in (key, "orders", "holdings", "data"):
                if isinstance(data.get(k), list):
                    return data[k]
        return []


class MainWindow(QMainWindow):
    def __init__(self, preloaded: dict = None):
        super().__init__()
        self.setWindowTitle("Super Trader")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(STYLE)
        self._holdings_data: list = []
        self._orders_data: list = []
        self._build_ui()

        if preloaded:
            # Populate immediately — no initial API call needed
            if preloaded.get("holdings") is not None:
                self._populate_holdings(preloaded["holdings"])
            if preloaded.get("orders") is not None:
                self._populate_orders(preloaded["orders"])
            if preloaded.get("funds"):
                self._update_metrics(preloaded["funds"])
            # Pass instruments to order panel if available
            op = getattr(self, "_order_panel", None)
            if op:
                if preloaded.get("equity"):
                    op._on_equity_loaded(preloaded["equity"])
                if preloaded.get("fno"):
                    op._on_fno_loaded(preloaded["fno"])
            # Start auto-refresh timer only (no immediate fetch)
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._refresh_data)
            self._timer.start(15_000)
        else:
            self._start_refresh()

        self.showMaximized()

    # ──────────────────────────────────────
    # Build UI
    # ──────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Top header bar
        header = self._build_header()
        main_layout.addWidget(header)

        # Metrics strip
        self.metrics_strip = self._build_metrics_strip()
        main_layout.addWidget(self.metrics_strip)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_holdings_tab(), "📊  Holdings")
        self.tabs.addTab(self._build_orders_tab(),   "📋  Orders")
        self.tabs.addTab(self._build_algo_tab(),     "🤖  Algo Engine")
        self.tabs.addTab(self._build_place_order_tab(), "➕  Place Order")
        main_layout.addWidget(self.tabs)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Connected  |  Auto-refresh: 15s")

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet("background-color: #0E0E18; border-bottom: 1px solid #252538;")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)

        logo = QLabel("📈  Super Trader")
        logo.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
        layout.addWidget(logo)
        layout.addStretch()

        refresh_btn = QPushButton("⟳  Refresh")
        refresh_btn.clicked.connect(self._refresh_data)
        layout.addWidget(refresh_btn)

        log_btn = QPushButton("📋  View Logs")
        log_btn.setStyleSheet("background-color: #1A2A3A; color: #5090CC; border-color: #2A4060;")
        log_btn.clicked.connect(self._open_log_file)
        layout.addWidget(log_btn)

        logout_btn = QPushButton("Logout")
        logout_btn.setStyleSheet(
            "background-color: #3A1515; color: #FF7777; border-color: #5A2525;")
        logout_btn.clicked.connect(self._logout)
        layout.addWidget(logout_btn)
        return header

    # Injected into every quick ref panel for consistent styling
    _QR_STYLE = (
        "<style>"
        "body{font-family:'Segoe UI',Arial,sans-serif;font-size:18px;"
        "color:#AAAACC;line-height:1.75;}"
        "b{color:#FFFFFF;font-weight:600;}"
        ".h{color:#5090CC;font-weight:bold;font-size:18px;"
        "display:block;margin-top:10px;margin-bottom:3px;"
        "border-bottom:1px solid #252538;padding-bottom:2px;}"
        "</style>"
    )

    def _build_quick_ref(self, html: str) -> QWidget:
        """
        Permanent expanded right-sidebar quick reference.
        Always visible, no toggle. Fixed width 220px.
        Consistent font/style injected automatically.
        """
        sidebar = QGroupBox("ℹ  Quick Reference")
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet(
            "QGroupBox{color:#5090CC;font-weight:bold;font-size:18px;"
            "border:1px solid #252538;border-radius:6px;margin-top:8px;background:#0A0A14;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}"
        )
        vlay = QVBoxLayout(sidebar)
        vlay.setContentsMargins(0, 4, 0, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background:transparent;border:none;")

        # Strip any embedded <style> from the content and inject the standard one
        import re as _re
        clean = _re.sub(r"<style[^>]*>.*?</style>", "", html, flags=_re.DOTALL).strip()
        full_html = self._QR_STYLE + clean

        lbl = QLabel(full_html)
        lbl.setTextFormat(Qt.RichText)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lbl.setContentsMargins(10, 8, 10, 8)
        lbl.setStyleSheet("background:transparent;")
        scroll.setWidget(lbl)
        vlay.addWidget(scroll)
        return sidebar

    def _build_metrics_strip(self) -> QWidget:
        strip = QWidget()
        strip.setFixedHeight(72)
        strip.setStyleSheet("background-color: #1C1C2A; border-bottom: 1px solid #252538;")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(40)

        self.metric_labels = {}
        metrics = [
            ("portfolio_value", "Portfolio Value", "₹0.00"),
            ("day_pnl",         "Day P&L",          "₹0.00"),
            ("total_pnl",       "Total P&L",        "₹0.00"),
            ("available_cash",  "Available Cash",   "₹0.00"),
        ]
        for key, label, default in metrics:
            col = QVBoxLayout()
            col.setSpacing(2)
            val_lbl = QLabel(default)
            val_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
            lbl = QLabel(label)
            lbl.setStyleSheet("font-size: 10px; color: #666680; text-transform: uppercase;")
            col.addWidget(val_lbl)
            col.addWidget(lbl)
            layout.addLayout(col)
            self.metric_labels[key] = val_lbl

        layout.addStretch()
        return strip

    # ──────────────────────────────────────
    # Holdings Tab
    # ──────────────────────────────────────

    def _build_holdings_tab(self) -> QWidget:
        w = QWidget()
        outer = QHBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Main content
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 8, 16)
        layout.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Current Holdings",
                             styleSheet="font-size:18px;font-weight:bold;color:#FFF;"))
        hdr.addStretch()
        sell_sel_btn = QPushButton("Sell Selected")
        sell_sel_btn.setStyleSheet(
            "background-color:#5A1A1A;color:#FF6060;border-color:#703030;")
        sell_sel_btn.clicked.connect(self._sell_selected_holding)
        hdr.addWidget(sell_sel_btn)
        layout.addLayout(hdr)

        self.holdings_table = QTableWidget()
        cols = ["Symbol", "Exchange", "Qty", "Avg Price", "LTP",
                "Current Value", "P&L", "P&L %", "Product", "Actions"]
        self.holdings_table.setColumnCount(len(cols))
        self.holdings_table.setHorizontalHeaderLabels(cols)
        self.holdings_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.holdings_table.horizontalHeader().setSectionResizeMode(9, QHeaderView.Fixed)
        self.holdings_table.setColumnWidth(9, 160)
        self.holdings_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.holdings_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.holdings_table.verticalHeader().setVisible(False)
        self.holdings_table.setAlternatingRowColors(True)
        layout.addWidget(self.holdings_table)

        outer.addWidget(content, 1)
        outer.addWidget(self._build_quick_ref(
            "<style>body{color:#AAAACC;font-size:18px;line-height:1.7;}"
            "b{color:#FFF;}.h{color:#5078DC;font-weight:bold;font-size:18px;}</style>"
            "<p class='h'>Column Meanings</p>"
            "<b>Qty</b> — shares you hold<br>"
            "<b>Avg Price</b> — average buy price<br>"
            "<b>LTP</b> — last traded price<br>"
            "<b>Current Value</b> — Qty × LTP<br>"
            "<b>P&amp;L</b> — Current Value − Cost<br>"
            "<b>P&amp;L %</b> — return percentage<br>"
            "<p class='h'>Product</p>"
            "<b>CNC</b> — delivery (overnight)<br>"
            "<b>MIS</b> — intraday only<br>"
            "<p class='h'>Actions</p>"
            "<b>Sell</b> — market sell now<br>"
            "<b>Modify</b> — custom sell order<br>"
            "<b>Sell Selected</b> — sell highlighted rows"
        ), 0)
        return w

    def _populate_holdings(self, holdings: list):
        self._holdings_data = holdings
        t = self.holdings_table
        t.setRowCount(len(holdings))

        for row, h in enumerate(holdings):
            # Normalise field names (API may use different casing)
            symbol   = h.get("tradingsymbol") or h.get("symbol", "")
            exchange = h.get("exchange", "NSE")
            qty      = str(h.get("quantity") or h.get("qty", 0))
            avg_price = float(h.get("average_price") or h.get("avg_price", 0))
            ltp      = float(h.get("last_price") or h.get("ltp", 0))
            cur_val  = float(h.get("current_value") or (ltp * float(qty or 0)))
            pnl      = float(h.get("pnl") or (cur_val - avg_price * float(qty or 0)))
            pnl_pct  = (pnl / (avg_price * float(qty or 1)) * 100) if avg_price else 0
            product  = h.get("product", "CNC")

            cells = [
                symbol,
                exchange,
                qty,
                f"₹{avg_price:,.2f}",
                f"₹{ltp:,.2f}",
                f"₹{cur_val:,.2f}",
                f"₹{pnl:,.2f}",
                f"{pnl_pct:+.2f}%",
                product,
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if col == 6 or col == 7:
                    item.setForeground(
                        QBrush(QColor("#40CC70") if pnl >= 0 else QColor("#FF5555")))
                t.setItem(row, col, item)

            # Action buttons cell
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(4)

            sell_btn = QPushButton("Sell")
            sell_btn.setFixedWidth(52)
            sell_btn.setStyleSheet("background:#5A1A1A;color:#FF6060;border-color:#703030;font-size:18px;")
            sell_btn.clicked.connect(lambda _, r=row: self._quick_sell(r))

            mod_btn = QPushButton("Modify")
            mod_btn.setFixedWidth(60)
            mod_btn.setStyleSheet("background:#1A3A5A;color:#50A0FF;border-color:#2A5070;font-size:18px;")
            mod_btn.clicked.connect(lambda _, r=row: self._modify_holding(r))

            action_layout.addWidget(sell_btn)
            action_layout.addWidget(mod_btn)
            t.setCellWidget(row, 9, action_widget)

    # ──────────────────────────────────────
    # Orders Tab  (3 sub-tabs)
    # ──────────────────────────────────────

    # Status classification
    ONGOING_STATUSES   = {"OPEN", "PENDING", "O-PENDING", "OPEN PENDING",
                          "TRIGGER PENDING", "AMO REQ RECEIVED"}
    COMPLETED_STATUSES = {"COMPLETE", "EXECUTED", "FILLED"}
    CANCELLED_STATUSES = {"CANCELLED", "REJECTED", "O-CANCELLED",
                          "CANCEL PENDING", "CANCELLED AMO"}

    STATUS_COLORS = {
        "COMPLETE":        "#40CC70", "EXECUTED":       "#40CC70", "FILLED": "#40CC70",
        "OPEN":            "#50A0FF", "PENDING":        "#50A0FF",
        "O-PENDING":       "#50A0FF", "OPEN PENDING":   "#50A0FF",
        "TRIGGER PENDING": "#FFB020", "AMO REQ RECEIVED": "#FFB020",
        "REJECTED":        "#FF5555",
        "CANCELLED":       "#888899", "O-CANCELLED":    "#888899",
        "CANCEL PENDING":  "#888899", "CANCELLED AMO":  "#888899",
    }

    def _build_orders_tab(self) -> QWidget:
        w = QWidget()
        outer = QHBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 8, 16)
        layout.setSpacing(10)

        # Header with Cancel All button
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Order Book",
                             styleSheet="font-size:18px;font-weight:bold;color:#FFF;"))
        hdr.addStretch()
        cancel_all_btn = QPushButton("Cancel All Open")
        cancel_all_btn.setStyleSheet("background:#3A1515;color:#FF8080;")
        cancel_all_btn.clicked.connect(self._cancel_all_orders)
        hdr.addWidget(cancel_all_btn)
        layout.addLayout(hdr)

        # Sub-tab bar styled as pill buttons
        sub_tab_row = QHBoxLayout()
        sub_tab_row.setSpacing(0)

        self._order_sub_tab = 0   # 0=ongoing 1=completed 2=cancelled
        self._order_sub_btns = []
        for i, label in enumerate(["🟡  Ongoing", "✅  Completed", "🚫  Cancelled"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setMinimumHeight(34)
            btn.setStyleSheet(self._sub_tab_style(i == 0))
            btn.clicked.connect(lambda _, idx=i: self._switch_order_sub_tab(idx))
            self._order_sub_btns.append(btn)
            sub_tab_row.addWidget(btn)
        sub_tab_row.addStretch()
        layout.addLayout(sub_tab_row)

        # Count badges
        self._order_count_labels = {}
        count_row = QHBoxLayout()
        for key, label in [("ongoing", "Ongoing"), ("completed", "Completed"), ("cancelled", "Cancelled")]:
            lbl = QLabel("0 orders")
            lbl.setStyleSheet("color:#555570;font-size:18px;")
            self._order_count_labels[key] = lbl
        self._order_count_lbl = QLabel("0 orders")
        self._order_count_lbl.setStyleSheet("color:#555570;font-size:18px;")
        count_row.addWidget(self._order_count_lbl)
        count_row.addStretch()
        layout.addLayout(count_row)

        # Single table — contents swapped on sub-tab change
        self.orders_table = self._make_orders_table(show_actions=True)
        layout.addWidget(self.orders_table)
        outer.addWidget(content, 1)
        outer.addWidget(self._build_quick_ref("""
<style>body{color:#AAAACC;font-size:18px;line-height:1.7;}b{color:#FFF;}.h{color:#5078DC;font-weight:bold;font-size:18px;}</style>
<p class="h">Statuses</p>
<b>O-Pending</b> — sent to exchange<br>
<b>Open</b> — live at exchange<br>
<b>Trigger Pending</b> — SL awaiting trigger<br>
<b>Complete</b> — fully filled<br>
<b>O-Cancelled</b> — cancelled<br>
<b>Rejected</b> — exchange rejected<br>
<p class="h">Order Types</p>
<b>MARKET</b> — best price now<br>
<b>LIMIT</b> — your price or better<br>
<b>SL</b> — stop-loss + limit<br>
<b>SL-M</b> — stop-loss at market<br>
<p class="h">Product</p>
<b>CNC</b> — delivery (overnight)<br>
<b>MIS</b> — intraday auto SQ-OFF<br>
<b>NRML</b> — F&amp;O overnight
"""), 0)
        return w

    def _sub_tab_style(self, active: bool) -> str:
        if active:
            return ("background:#252545;color:#FFFFFF;border:1px solid #4060C8;"
                    "border-bottom:2px solid #4060C8;font-weight:bold;font-size:18px;padding:6px 18px;")
        return ("background:#1C1C2A;color:#888899;border:1px solid #252538;"
                "font-size:18px;padding:6px 18px;")

    def _make_orders_table(self, show_actions: bool) -> QTableWidget:
        cols = ["Order ID", "Symbol", "Exchange", "Type", "Side",
                "Qty", "Price", "Status", "Product"]
        if show_actions:
            cols.append("Actions")
        t = QTableWidget()
        t.setColumnCount(len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        if show_actions:
            t.horizontalHeader().setSectionResizeMode(9, QHeaderView.Fixed)
            t.setColumnWidth(9, 180)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        return t

    def _switch_order_sub_tab(self, idx: int):
        self._order_sub_tab = idx
        for i, btn in enumerate(self._order_sub_btns):
            btn.setChecked(i == idx)
            btn.setStyleSheet(self._sub_tab_style(i == idx))
        # Show Actions column only for Ongoing (idx 0), hide for Completed/Cancelled
        self.orders_table.setColumnHidden(9, idx != 0)
        self._repopulate_orders_table()

    def _populate_orders(self, orders: list):
        self._orders_data = orders
        # Pre-classify into buckets
        self._orders_ongoing   = [o for o in orders
            if (o.get("status") or "").upper().strip() in self.ONGOING_STATUSES]
        self._orders_completed = [o for o in orders
            if (o.get("status") or "").upper().strip() in self.COMPLETED_STATUSES]
        self._orders_cancelled = [o for o in orders
            if (o.get("status") or "").upper().strip() in self.CANCELLED_STATUSES]

        # Update count label
        counts = {
            "ongoing":   len(self._orders_ongoing),
            "completed": len(self._orders_completed),
            "cancelled": len(self._orders_cancelled),
        }
        keys = ["ongoing", "completed", "cancelled"]
        self._order_count_lbl.setText(
            f"{counts[keys[self._order_sub_tab]]} orders"
        )
        # Update sub-tab button labels with counts
        labels = ["🟡  Ongoing", "✅  Completed", "🚫  Cancelled"]
        count_vals = [counts["ongoing"], counts["completed"], counts["cancelled"]]
        for i, (btn, lbl, cnt) in enumerate(zip(self._order_sub_btns, labels, count_vals)):
            btn.setText(f"{lbl}  ({cnt})")

        self._repopulate_orders_table()

    def _repopulate_orders_table(self):
        buckets = [
            getattr(self, "_orders_ongoing",   []),
            getattr(self, "_orders_completed", []),
            getattr(self, "_orders_cancelled", []),
        ]
        show_actions = (self._order_sub_tab == 0)  # only ongoing needs actions
        self.orders_table.setColumnHidden(9, not show_actions)
        orders = buckets[self._order_sub_tab]

        # Update count label
        self._order_count_lbl.setText(f"{len(orders)} orders")

        t = self.orders_table
        t.setRowCount(len(orders))

        for row, o in enumerate(orders):
            order_id = o.get("order_id", "")
            symbol   = o.get("tradingsymbol") or o.get("symbol", "")
            exchange = o.get("exchange", "")
            otype    = o.get("order_type", "")
            side     = o.get("transaction_type", "")
            qty      = str(o.get("quantity", ""))
            price    = str(o.get("price", "0"))
            status   = (o.get("status", "") or "").upper().strip()
            product  = o.get("product", "")

            cells = [order_id, symbol, exchange, otype, side, qty, price, status, product]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                if col == 7:
                    color = self.STATUS_COLORS.get(status, "#DCDCE6")
                    item.setForeground(QBrush(QColor(color)))
                if col == 4:
                    item.setForeground(QBrush(
                        QColor("#40CC70") if side == "BUY" else QColor("#FF5555")))
                t.setItem(row, col, item)

            # Actions column — only for ongoing orders
            if show_actions and t.columnCount() > 9:
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(4, 2, 4, 2)
                action_layout.setSpacing(4)

                cancel_btn = QPushButton("Cancel")
                cancel_btn.setMinimumWidth(65)
                cancel_btn.setMinimumHeight(28)
                cancel_btn.setStyleSheet("background:#3A1515;color:#FF6060;font-size:18px;padding:2px 6px;")
                cancel_btn.clicked.connect(lambda _, oid=order_id: self._cancel_order(oid))

                mod_btn = QPushButton("Modify")
                mod_btn.setMinimumWidth(65)
                mod_btn.setMinimumHeight(28)
                mod_btn.setStyleSheet("background:#1A3A5A;color:#50A0FF;font-size:18px;padding:2px 6px;")
                mod_btn.clicked.connect(lambda _, oid=order_id: self._modify_order_by_id(oid))

                action_layout.addWidget(cancel_btn)
                action_layout.addWidget(mod_btn)
                t.setRowHeight(row, 36)
                t.setCellWidget(row, 9, action_widget)
            else:
                t.setRowHeight(row, 36)

    # ──────────────────────────────────────
    # Algo Engine Tab
    # ──────────────────────────────────────

    def _build_algo_tab(self) -> QWidget:
        from ui.algo_panel import AlgoPanel
        w = QWidget()
        outer = QHBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._algo_panel = AlgoPanel()
        outer.addWidget(self._algo_panel, 1)
        outer.addWidget(self._build_quick_ref("""
<style>body{color:#AAAACC;font-size:18px;line-height:1.7;}b{color:#FFF;}.h{color:#5078DC;font-weight:bold;font-size:18px;}</style>
<p class="h">Strategies</p>
<b>MA Crossover</b> — buy when short MA crosses above long MA<br>
<b>RSI</b> — buy when oversold, sell when overbought<br>
<b>Price Level</b> — buy/sell at specific price targets<br>
<p class="h">Key Terms</p>
<b>MA</b> — Moving Average<br>
<b>RSI</b> — Relative Strength Index (0–100)<br>
<b>Overbought</b> — RSI &gt; 70, possible pullback<br>
<b>Oversold</b> — RSI &lt; 30, possible bounce<br>
<b>Scan Interval</b> — check frequency (seconds)<br>
<p class="h">Signal Colours</p>
<b style="color:#50DD80;">Green</b> — BUY placed<br>
<b style="color:#FF6060;">Red</b> — SELL placed<br>
<b style="color:#FF8800;">Orange</b> — strategy error
"""), 0)
        return w

    # ──────────────────────────────────────
    # Place Order Tab
    # ──────────────────────────────────────

    def _build_place_order_tab(self) -> QWidget:
        # OrderPanel has its own built-in quick reference sidebar
        from ui.order_panel import OrderPanel
        self._order_panel = OrderPanel()
        self._order_panel.order_placed.connect(self._on_order_placed)
        return self._order_panel

    # ──────────────────────────────────────
    # Data refresh
    # ──────────────────────────────────────

    def _start_refresh(self):
        self._refresh_data()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_data)
        self._timer.start(15_000)   # every 15 seconds

    def _refresh_data(self):
        self.status_bar.showMessage("Refreshing data…")
        self._worker = DataWorker("all")
        self._worker.holdings_ready.connect(self._populate_holdings)
        self._worker.orders_ready.connect(self._populate_orders)
        self._worker.funds_ready.connect(self._update_metrics)
        self._worker.error.connect(self._on_data_error)
        self._worker.finished.connect(
            lambda: self.status_bar.showMessage("Last updated: just now  |  Auto-refresh: 15s"))
        self._worker.start()

    def _update_metrics(self, raw: dict):
        """
        Parse fund summary. Handles all SDK response shapes:

        Shape A (our APIClient envelope):
          {"success": True, "data": [{"AVAILABLE_BALANCE": "...", ...}, ...]}

        Shape B (direct API, data is a list of segment dicts):
          {"status": "success", "data": [{"AVAILABLE_BALANCE": ..., ...}]}

        Shape C (data is a flat dict):
          {"status": "success", "data": {"AVAILABLE_BALANCE": ..., ...}}

        Official fields from mStock docs:
          AVAILABLE_BALANCE  — cash available to trade
          SUM_OF_ALL         — total account value
          REALISED_PROFITS   — realised P&L
          MTM_COMBINED       — day mark-to-market P&L
        """
        def _f(v) -> float:
            try:
                return float(v or 0)
            except (TypeError, ValueError):
                return 0.0

        # Unwrap envelope: our client adds {"success":..., "data":...}
        if isinstance(raw, dict) and "success" in raw:
            inner = raw.get("data", {})
        elif isinstance(raw, dict) and "status" in raw:
            inner = raw.get("data", {})
        else:
            inner = raw

        # Normalise inner into a list of segment dicts
        if isinstance(inner, list):
            segments = inner
        elif isinstance(inner, dict):
            nested = inner.get("data", inner)
            segments = nested if isinstance(nested, list) else [nested]
        else:
            segments = []

        # Flatten all segments (one per margin segment A/E/etc.) by summing numerics
        flat: dict = {}
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            for k, v in seg.items():
                try:
                    flat[k] = flat.get(k, 0.0) + float(v)
                except (TypeError, ValueError):
                    if k not in flat:
                        flat[k] = v

        import logging as _log
        _log.getLogger(__name__).info("fund flat keys: %s", list(flat.keys()))

        # No data at all — API call failed or returned empty
        if not flat:
            for lbl in self.metric_labels.values():
                lbl.setText("N/A")
                lbl.setStyleSheet("font-size:18px;font-weight:bold;color:#888899;")
            return

        # _pick returns (value, found) — lets us distinguish "0" from "missing"
        def _pick(*keys):
            for k in keys:
                if k in flat:
                    try:
                        return float(flat[k] or 0), True
                    except (TypeError, ValueError):
                        pass
            return 0.0, False

        cash,  cf = _pick("AVAILABLE_BALANCE",  "available_balance",  "available_cash")
        total, tf = _pick("SUM_OF_ALL",          "sum_of_all",         "net_value")
        tpnl,  pf = _pick("REALISED_PROFITS",    "realised_profits",   "realised_pnl")
        dpnl,  df = _pick("MTM_COMBINED",        "mtm_combined",       "unrealised_profit")

        _log.getLogger(__name__).info(
            "Metrics: cash=%.2f(found=%s) total=%.2f(found=%s) tpnl=%.2f(found=%s) dpnl=%.2f(found=%s)",
            cash, cf, total, tf, tpnl, pf, dpnl, df
        )

        def _fmt(v, found):
            return f"₹{v:,.2f}" if found else "N/A"

        self.metric_labels["portfolio_value"].setText(_fmt(total, tf))
        self.metric_labels["day_pnl"].setText(_fmt(dpnl, df))
        self.metric_labels["total_pnl"].setText(_fmt(tpnl, pf))
        self.metric_labels["available_cash"].setText(_fmt(cash, cf))

        for key, val, found in (("day_pnl", dpnl, df), ("total_pnl", tpnl, pf)):
            if found:
                color = "#40CC70" if val >= 0 else "#FF5555"
            else:
                color = "#888899"
            self.metric_labels[key].setStyleSheet(
                f"font-size:18px;font-weight:bold;color:{color};")
    # ──────────────────────────────────────
    # Actions
    # ──────────────────────────────────────

    def _quick_sell(self, row: int):
        if row >= len(self._holdings_data):
            return
        h = self._holdings_data[row]
        symbol = h.get("tradingsymbol") or h.get("symbol", "")
        qty    = str(h.get("quantity") or h.get("qty", 1))
        exchange = h.get("exchange", "NSE")
        product  = h.get("product", "CNC")

        reply = QMessageBox.question(
            self, "Confirm Sell",
            f"Sell {qty} units of {symbol} at market price?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            result = APIClient.get().place_order(
                "regular", symbol, exchange, "SELL",
                "MARKET", qty, product, "DAY",
                "0", "0", "0", "",
            )
            if result["success"]:
                QMessageBox.information(self, "Order Placed",
                                        f"Sell order placed for {symbol}")
                self._refresh_data()
            else:
                QMessageBox.warning(self, "Error", result.get("error", "Failed"))

    def _sell_selected_holding(self):
        rows = set(i.row() for i in self.holdings_table.selectedItems())
        if not rows:
            QMessageBox.information(self, "No Selection", "Select a holding to sell.")
            return
        for row in rows:
            self._quick_sell(row)

    def _modify_holding(self, row: int):
        if row >= len(self._holdings_data):
            return
        h = self._holdings_data[row]
        from ui.modify_dialog import ModifyHoldingDialog
        dlg = ModifyHoldingDialog(h, self)
        if dlg.exec_():
            self._refresh_data()

    def _modify_order(self, row: int):
        if row >= len(self._orders_data):
            return
        o = self._orders_data[row]
        from ui.modify_dialog import ModifyOrderDialog
        dlg = ModifyOrderDialog(o, self)
        if dlg.exec_():
            self._refresh_data()

    def _modify_order_by_id(self, order_id: str):
        """Lookup order by ID — safe after table refresh unlike row index."""
        o = next((x for x in self._orders_data
                  if x.get("order_id") == order_id), None)
        if o is None:
            return
        from ui.modify_dialog import ModifyOrderDialog
        dlg = ModifyOrderDialog(o, self)
        if dlg.exec_():
            self._refresh_data()

    def _cancel_order(self, order_id: str):
        reply = QMessageBox.question(
            self, "Confirm Cancel",
            f"Cancel order {order_id}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            result = APIClient.get().cancel_order(order_id)
            if result["success"]:
                QMessageBox.information(self, "Cancelled",
                                        f"Order {order_id} cancelled")
                self._refresh_data()
            else:
                QMessageBox.warning(self, "Error", result.get("error", "Failed"))

    def _cancel_all_orders(self):
        # Check if there are any ongoing orders to cancel
        ongoing = getattr(self, "_orders_ongoing", [])
        if not ongoing:
            QMessageBox.information(
                self, "No Open Orders",
                "There are no open orders to cancel."
            )
            return

        reply = QMessageBox.question(
            self, "Confirm",
            f"Cancel ALL {len(ongoing)} open order(s)?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                APIClient.get()._mconnect.cancel_all()
                self._refresh_data()
                QMessageBox.information(self, "Done", "All open orders have been cancelled.")
            except Exception as e:
                err = str(e)
                if "no open order" in err.lower() or "does not exist" in err.lower():
                    QMessageBox.information(self, "No Open Orders",
                                            "There are no open orders to cancel.")
                else:
                    QMessageBox.warning(self, "Error", err)

    def _on_order_placed(self, result: dict):
        if result["success"]:
            self._refresh_data()
        else:
            QMessageBox.warning(self, "Order Failed", result.get("error", "Unknown error"))

    def _on_data_error(self, error: str):
        """Handle data fetch errors — show IP whitelist popup if that's the cause."""
        self.status_bar.showMessage(f"Error: {error}")

        if "ip address" in error.lower() or "ip" in error.lower() and "match" in error.lower():
            # Fetch current public IP to show in the popup
            try:
                import urllib.request
                current_ip = urllib.request.urlopen(
                    "https://api.ipify.org", timeout=4
                ).read().decode().strip()
            except Exception:
                current_ip = "Unable to detect — visit whatismyip.com"

            QMessageBox.warning(
                self,
                "IP Address Not Whitelisted",
                f"<b>mStock API Error:</b><br>"
                f"Primary and Secondary IP Address are not matching "
                f"with current IP address.<br><br>"
                f"<b>Your current public IP:</b><br>"
                f"<code style='font-size:18px;'>{current_ip}</code><br><br>"
                f"<b>Steps to fix:</b><br>"
                f"1. Go to <b>trade.mstock.com</b><br>"
                f"2. Menu → Products → <b>Trading APIs</b><br>"
                f"3. Click <b>API Settings</b><br>"
                f"4. Add <b>{current_ip}</b> as Primary or Secondary IP<br>"
                f"5. Save and restart Super Trader<br><br>"
                f"<i>No API exists to update this automatically —<br>"
                f"please contact the mStock team if the issue persists:<br>"
                f"tradingapi@mstock.com</i>",
            )

    def _open_log_file(self):
        """Open the log file in the system default text editor."""
        import os, sys
        from pathlib import Path

        if getattr(sys, "frozen", False):
            log_file = Path(sys.executable).parent / "super_trader.log"
        else:
            log_file = Path(__file__).resolve().parent.parent / "super_trader.log"

        if not log_file.exists():
            QMessageBox.information(
                self, "Log File",
                f"Log file not found yet at:\n{log_file}\n\n"
                "It will be created when the app performs its first API call."
            )
            return

        # Show path and open with system default
        try:
            if sys.platform == "win32":
                os.startfile(str(log_file))
            elif sys.platform == "darwin":
                os.system(f'open "{log_file}"')
            else:
                os.system(f'xdg-open "{log_file}"')
        except Exception as e:
            QMessageBox.information(
                self, "Log File Location",
                f"Log file is at:\n{log_file}\n\n"
                f"Open it in any text editor (Notepad, VS Code, etc.)\n\n"
                f"(Auto-open failed: {e})"
            )

    def _logout(self):
        reply = QMessageBox.question(
            self, "Logout", "Logout and exit?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._timer.stop()
            APIClient.get().logout()
            clear_credentials()
            QApplication.quit()

    def closeEvent(self, event):
        self._timer.stop()
        APIClient.get().logout()
        event.accept()
