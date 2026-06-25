"""
ui/main_window.py
The main application window after authentication.
Tabs: Holdings | Orders | Algo Engine | Place Order
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QSplitter,
    QStatusBar, QFrame, QMessageBox, QApplication
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
                # API returns data as a list of segment dicts (A, E, etc.)
                # Flatten all segments into one dict by summing numeric fields
                raw = r.get("data", {})
                segments = raw if isinstance(raw, list) else (
                    raw.get("data", []) if isinstance(raw, dict) else []
                )
                flat: dict = {}
                for seg in (segments if isinstance(segments, list) else []):
                    if isinstance(seg, dict):
                        for k, v in seg.items():
                            try:
                                flat[k] = flat.get(k, 0.0) + float(v)
                            except (TypeError, ValueError):
                                if k not in flat:
                                    flat[k] = v
                self.funds_ready.emit(flat)
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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SuperTrader")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(STYLE)
        self._holdings_data: list = []
        self._orders_data: list = []
        self._build_ui()
        self._start_refresh()
        # FIX #3: always start maximized (caller may also call showMaximized)
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
        self.status_bar.showMessage("Connected  |  Auto-refresh: 60s")

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet("background-color: #0E0E18; border-bottom: 1px solid #252538;")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)

        logo = QLabel("📈  mStock Trader")
        logo.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
        layout.addWidget(logo)
        layout.addStretch()

        refresh_btn = QPushButton("⟳  Refresh")
        refresh_btn.clicked.connect(self._refresh_data)
        layout.addWidget(refresh_btn)

        logout_btn = QPushButton("Logout")
        logout_btn.setStyleSheet(
            "background-color: #3A1515; color: #FF7777; border-color: #5A2525;")
        logout_btn.clicked.connect(self._logout)
        layout.addWidget(logout_btn)
        return header

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
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Current Holdings",
                             styleSheet="font-size:14px;font-weight:bold;color:#FFF;"))
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
            sell_btn.setStyleSheet("background:#5A1A1A;color:#FF6060;border-color:#703030;font-size:11px;")
            sell_btn.clicked.connect(lambda _, r=row: self._quick_sell(r))

            mod_btn = QPushButton("Modify")
            mod_btn.setFixedWidth(60)
            mod_btn.setStyleSheet("background:#1A3A5A;color:#50A0FF;border-color:#2A5070;font-size:11px;")
            mod_btn.clicked.connect(lambda _, r=row: self._modify_holding(r))

            action_layout.addWidget(sell_btn)
            action_layout.addWidget(mod_btn)
            t.setCellWidget(row, 9, action_widget)

    # ──────────────────────────────────────
    # Orders Tab
    # ──────────────────────────────────────

    def _build_orders_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Order Book",
                             styleSheet="font-size:14px;font-weight:bold;color:#FFF;"))
        hdr.addStretch()
        cancel_all_btn = QPushButton("Cancel All Open")
        cancel_all_btn.setStyleSheet("background:#3A1515;color:#FF8080;")
        cancel_all_btn.clicked.connect(self._cancel_all_orders)
        hdr.addWidget(cancel_all_btn)
        layout.addLayout(hdr)

        self.orders_table = QTableWidget()
        cols = ["Order ID", "Symbol", "Exchange", "Type", "Side",
                "Qty", "Price", "Status", "Product", "Actions"]
        self.orders_table.setColumnCount(len(cols))
        self.orders_table.setHorizontalHeaderLabels(cols)
        self.orders_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.orders_table.horizontalHeader().setSectionResizeMode(9, QHeaderView.Fixed)
        self.orders_table.setColumnWidth(9, 160)
        self.orders_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.orders_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.orders_table.verticalHeader().setVisible(False)
        self.orders_table.setAlternatingRowColors(True)
        layout.addWidget(self.orders_table)
        return w

    def _populate_orders(self, orders: list):
        self._orders_data = orders
        t = self.orders_table
        t.setRowCount(len(orders))

        STATUS_COLORS = {
            "COMPLETE": "#40CC70", "EXECUTED": "#40CC70",
            "OPEN": "#50A0FF",     "PENDING": "#50A0FF",
            "REJECTED": "#FF5555", "CANCELLED": "#888899",
        }

        for row, o in enumerate(orders):
            order_id = o.get("order_id", "")
            symbol   = o.get("tradingsymbol") or o.get("symbol", "")
            exchange = o.get("exchange", "")
            otype    = o.get("order_type", "")
            side     = o.get("transaction_type", "")
            qty      = str(o.get("quantity", ""))
            price    = str(o.get("price", "0"))
            status   = (o.get("status", "") or "").upper()
            product  = o.get("product", "")

            cells = [order_id, symbol, exchange, otype, side, qty, price, status, product]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                if col == 7:
                    color = STATUS_COLORS.get(status, "#DCDCE6")
                    item.setForeground(QBrush(QColor(color)))
                if col == 4:
                    item.setForeground(QBrush(
                        QColor("#40CC70") if side == "BUY" else QColor("#FF5555")))
                t.setItem(row, col, item)

            # Actions
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(4)

            cancel_btn = QPushButton("Cancel")
            cancel_btn.setFixedWidth(60)
            cancel_btn.setStyleSheet("background:#3A1515;color:#FF6060;font-size:11px;")
            cancel_btn.setEnabled(status in ("OPEN", "PENDING", "TRIGGER PENDING"))
            cancel_btn.clicked.connect(lambda _, oid=order_id: self._cancel_order(oid))

            mod_btn = QPushButton("Modify")
            mod_btn.setFixedWidth(60)
            mod_btn.setStyleSheet("background:#1A3A5A;color:#50A0FF;font-size:11px;")
            mod_btn.setEnabled(status in ("OPEN", "PENDING", "TRIGGER PENDING"))
            mod_btn.clicked.connect(lambda _, r=row: self._modify_order(r))

            action_layout.addWidget(cancel_btn)
            action_layout.addWidget(mod_btn)
            t.setCellWidget(row, 9, action_widget)

    # ──────────────────────────────────────
    # Algo Engine Tab
    # ──────────────────────────────────────

    def _build_algo_tab(self) -> QWidget:
        from ui.algo_panel import AlgoPanel
        self._algo_panel = AlgoPanel()
        return self._algo_panel

    # ──────────────────────────────────────
    # Place Order Tab
    # ──────────────────────────────────────

    def _build_place_order_tab(self) -> QWidget:
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
        self._timer.start(60_000)   # every 60 seconds

    def _refresh_data(self):
        self.status_bar.showMessage("Refreshing data…")
        self._worker = DataWorker("all")
        self._worker.holdings_ready.connect(self._populate_holdings)
        self._worker.orders_ready.connect(self._populate_orders)
        self._worker.funds_ready.connect(self._update_metrics)
        self._worker.error.connect(lambda e: self.status_bar.showMessage(f"Error: {e}"))
        self._worker.finished.connect(
            lambda: self.status_bar.showMessage("Last updated: just now  |  Auto-refresh: 60s"))
        self._worker.start()

    def _update_metrics(self, funds: dict):
        """
        mStock fund summary API field names (UPPERCASE, from docs):
          AVAILABLE_BALANCE  -> available cash
          SUM_OF_ALL         -> total ledger value
          REALISED_PROFITS   -> realised P&L
          MTM_COMBINED       -> day mark-to-market P&L
        """
        def _f(val) -> float:
            try:
                return float(val or 0)
            except (TypeError, ValueError):
                return 0.0

        cash  = _f(funds.get("AVAILABLE_BALANCE"))
        total = _f(funds.get("SUM_OF_ALL"))
        tpnl  = _f(funds.get("REALISED_PROFITS"))
        dpnl  = _f(funds.get("MTM_COMBINED"))

        self.metric_labels["portfolio_value"].setText(f"\u20b9{total:,.2f}")
        self.metric_labels["day_pnl"].setText(f"\u20b9{dpnl:,.2f}")
        self.metric_labels["total_pnl"].setText(f"\u20b9{tpnl:,.2f}")
        self.metric_labels["available_cash"].setText(f"\u20b9{cash:,.2f}")

        for key, val in (("day_pnl", dpnl), ("total_pnl", tpnl)):
            color = "#40CC70" if val >= 0 else "#FF5555"
            self.metric_labels[key].setStyleSheet(
                f"font-size:15px;font-weight:bold;color:{color};")


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
        reply = QMessageBox.question(
            self, "Confirm", "Cancel ALL open orders?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                APIClient.get()._mconnect.cancel_all()
                self._refresh_data()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _on_order_placed(self, result: dict):
        if result["success"]:
            self._refresh_data()
        else:
            QMessageBox.warning(self, "Order Failed", result.get("error", "Unknown error"))

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
