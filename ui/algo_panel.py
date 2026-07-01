"""
ui/algo_panel.py
Algo Engine management UI.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QSpinBox,
    QDoubleSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QFormLayout, QMessageBox,
    QFrame, QTextEdit
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QBrush

from algo.engine import get_engine, MovingAverageCrossStrategy, RSIOverboughtStrategy, PriceLevelStrategy, BracketGuardStrategy

STRATEGY_MAP = {
    "Moving Average Crossover": MovingAverageCrossStrategy,
    "RSI Overbought/Oversold":  RSIOverboughtStrategy,
    "Price Level Trigger":      PriceLevelStrategy,
    "Bracket Guard (Target+SL)": BracketGuardStrategy,
}


class AlgoPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._engine = get_engine()
        self._engine.on_signal = self._on_signal
        self._engine.on_error  = self._on_error
        self._log_messages: list[str] = []
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Left: config panel
        left = QVBoxLayout()
        left.setSpacing(12)

        # Strategy builder
        builder_box = QGroupBox("Add Strategy")
        builder_box.setStyleSheet("QGroupBox { color: #AAAACC; font-weight:bold; font-size:15px;"
                                  " border:1px solid #252538; border-radius:6px; margin-top:8px; }"
                                  " QGroupBox::title { subcontrol-origin:margin; left:8px; }")
        form = QFormLayout(builder_box)
        form.setSpacing(10)
        form.setContentsMargins(12, 16, 12, 12)

        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(list(STRATEGY_MAP.keys()))
        self.strategy_combo.currentTextChanged.connect(self._update_params)
        form.addRow("Strategy:", self.strategy_combo)

        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("e.g. INFY")
        self.symbol_input.setText("INFY")
        form.addRow("Symbol:", self.symbol_input)

        self.exchange_combo = QComboBox()
        self.exchange_combo.addItems(["NSE", "BSE"])
        form.addRow("Exchange:", self.exchange_combo)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 100000)
        self.qty_spin.setValue(1)
        form.addRow("Quantity:", self.qty_spin)

        self.product_combo = QComboBox()
        self.product_combo.addItems(["CNC", "MIS", "NRML"])
        form.addRow("Product:", self.product_combo)

        # Dynamic params
        self.short_spin = QSpinBox()
        self.short_spin.setRange(1, 200); self.short_spin.setValue(5)
        self.long_spin  = QSpinBox()
        self.long_spin.setRange(1, 500);  self.long_spin.setValue(20)
        self.rsi_period = QSpinBox()
        self.rsi_period.setRange(2, 100); self.rsi_period.setValue(14)
        self.rsi_ob    = QSpinBox()
        self.rsi_ob.setRange(50, 99);     self.rsi_ob.setValue(70)
        self.rsi_os    = QSpinBox()
        self.rsi_os.setRange(1, 49);      self.rsi_os.setValue(30)
        self.buy_price  = QDoubleSpinBox()
        self.buy_price.setRange(0, 1e7);  self.buy_price.setDecimals(2)
        self.sell_price = QDoubleSpinBox()
        self.sell_price.setRange(0, 1e7); self.sell_price.setDecimals(2)
        self.target_pct = QDoubleSpinBox()
        self.target_pct.setRange(0.01, 100); self.target_pct.setDecimals(2)
        self.target_pct.setValue(0.9); self.target_pct.setSuffix(" %")
        self.sl_pct = QDoubleSpinBox()
        self.sl_pct.setRange(0.01, 100); self.sl_pct.setDecimals(2)
        self.sl_pct.setValue(0.9); self.sl_pct.setSuffix(" %")

        self._param_rows = {
            "short_window": ("Short MA Window:", self.short_spin),
            "long_window":  ("Long MA Window:",  self.long_spin),
            "rsi_period":   ("RSI Period:",      self.rsi_period),
            "rsi_ob":       ("Overbought Level:",self.rsi_ob),
            "rsi_os":       ("Oversold Level:",  self.rsi_os),
            "buy_price":    ("Buy Price (₹):",   self.buy_price),
            "sell_price":   ("Sell Price (₹):",  self.sell_price),
            "target_pct":   ("Target % (+):",    self.target_pct),
            "sl_pct":       ("Stop-Loss % (-):", self.sl_pct),
        }
        for label, widget in self._param_rows.values():
            form.addRow(label, widget)

        self._update_params(self.strategy_combo.currentText())

        interval_spin = QSpinBox()
        interval_spin.setRange(5, 3600); interval_spin.setValue(60)
        interval_spin.setSuffix(" sec")
        interval_spin.valueChanged.connect(lambda v: setattr(self._engine, 'interval', v))
        form.addRow("Scan Interval:", interval_spin)

        add_btn = QPushButton("➕  Add Strategy")
        add_btn.setStyleSheet("background:#1A5A30;color:#50DD80;border-color:#2A7040;font-weight:bold;")
        add_btn.clicked.connect(self._add_strategy)
        form.addRow("", add_btn)

        left.addWidget(builder_box)

        # Engine controls
        ctrl_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶  Start Engine")
        self.start_btn.setStyleSheet("background:#1A3A5A;color:#50A0FF;font-weight:bold;")
        self.start_btn.clicked.connect(self._toggle_engine)

        self.engine_status = QLabel("● Stopped")
        self.engine_status.setStyleSheet("color:#FF5555;font-size:15px;font-weight:bold;")

        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.engine_status)
        ctrl_layout.addStretch()
        left.addLayout(ctrl_layout)
        left.addStretch()

        layout.addLayout(left, 1)

        # Right: strategy list + log
        right = QVBoxLayout()
        right.setSpacing(12)

        strat_label = QLabel("Active Strategies")
        strat_label.setStyleSheet("font-size:16px;font-weight:bold;color:#FFF;")
        right.addWidget(strat_label)

        self.strat_table = QTableWidget()
        self.strat_table.setColumnCount(6)
        self.strat_table.setHorizontalHeaderLabels(
            ["Strategy", "Symbol", "Exchange", "Qty", "Product", "Remove"])
        self.strat_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.strat_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.strat_table.setColumnWidth(5, 80)
        self.strat_table.verticalHeader().setVisible(False)
        self.strat_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.strat_table.setFixedHeight(180)
        right.addWidget(self.strat_table)

        log_label = QLabel("Signal Log")
        log_label.setStyleSheet("font-size:16px;font-weight:bold;color:#FFF;")
        right.addWidget(log_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "background:#0E0E18;color:#AAFFAA;font-family:monospace;font-size:15px;"
            "border:1px solid #252538;border-radius:4px;")
        right.addWidget(self.log_view)

        layout.addLayout(right, 2)

    def _update_params(self, strategy_name: str):
        ma_params      = ["short_window", "long_window"]
        rsi_params     = ["rsi_period", "rsi_ob", "rsi_os"]
        price_params   = ["buy_price", "sell_price"]
        bracket_params = ["target_pct", "sl_pct"]

        show_keys = (
            ma_params      if strategy_name == "Moving Average Crossover"
            else rsi_params     if strategy_name == "RSI Overbought/Oversold"
            else bracket_params if strategy_name == "Bracket Guard (Target+SL)"
            else price_params
        )
        form = self.strategy_combo.parent().layout()
        for key, (label, widget) in self._param_rows.items():
            widget.setVisible(key in show_keys)
            for i in range(form.rowCount()):
                item = form.itemAt(i, QFormLayout.LabelRole)
                if item and item.widget() and item.widget().text() == label:
                    item.widget().setVisible(key in show_keys)

    def _add_strategy(self):
        name     = self.strategy_combo.currentText()
        symbol   = self.symbol_input.text().strip().upper()
        exchange = self.exchange_combo.currentText()
        qty      = self.qty_spin.value()
        product  = self.product_combo.currentText()

        if not symbol:
            QMessageBox.warning(self, "Error", "Symbol is required")
            return

        cls = STRATEGY_MAP[name]
        if name == "Moving Average Crossover":
            s = cls(symbol, exchange, qty, product,
                    short_window=self.short_spin.value(),
                    long_window=self.long_spin.value())
        elif name == "RSI Overbought/Oversold":
            s = cls(symbol, exchange, qty, product,
                    period=self.rsi_period.value(),
                    overbought=self.rsi_ob.value(),
                    oversold=self.rsi_os.value())
        elif name == "Bracket Guard (Target+SL)":
            s = cls(symbol, exchange, qty, product,
                    target_pct=self.target_pct.value(),
                    sl_pct=self.sl_pct.value())
        else:
            s = cls(symbol, exchange, qty, product,
                    buy_price=self.buy_price.value(),
                    sell_price=self.sell_price.value())

        self._engine.add_strategy(s)
        self._refresh_strat_table()
        self._log(f"[ADD] {name} → {symbol} ({exchange}) qty={qty}")
        from algo.engine import BracketGuardStrategy as _BGS
        if isinstance(s, _BGS):
            if not self._engine._running:
                self._engine.start()
                self._update_engine_btn(running=True)
            self._log(
                '<span style="color:#50A0FF">[BracketGuard] ' +
                f'Auto-monitoring {symbol} — reacts within 0.5s of holding appearing</span>'
            )

    def _refresh_strat_table(self):
        strategies = self._engine.strategies
        t = self.strat_table
        t.setRowCount(len(strategies))
        for row, s in enumerate(strategies):
            cells = [
                type(s).__name__, s.symbol, s.exchange,
                s.quantity, s.product
            ]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                t.setItem(row, col, item)

            rm_btn = QPushButton("✕")
            rm_btn.setStyleSheet("background:#3A1515;color:#FF6060;font-size:15px;")
            rm_btn.clicked.connect(lambda _, r=row: self._remove_strategy(r))
            t.setCellWidget(row, 5, rm_btn)

    def _remove_strategy(self, row: int):
        self._engine.remove_strategy(row)
        self._refresh_strat_table()
        self._log(f"[REMOVE] Strategy #{row} removed")

    def _update_engine_btn(self, running: bool):
        if running:
            self.start_btn.setText("■  Stop Engine")
            self.start_btn.setStyleSheet("background:#5A1A1A;color:#FF6060;font-weight:bold;")
            self.engine_status.setText("● Running")
            self.engine_status.setStyleSheet("color:#40CC70;font-weight:bold;")
        else:
            self.start_btn.setText("▶  Start Engine")
            self.start_btn.setStyleSheet("background:#1A3A5A;color:#50A0FF;font-weight:bold;")
            self.engine_status.setText("● Stopped")
            self.engine_status.setStyleSheet("color:#FF5555;font-weight:bold;")

    def _toggle_engine(self):
        if self._engine._running:
            self._engine.stop()
            self.start_btn.setText("▶  Start Engine")
            self.start_btn.setStyleSheet("background:#1A3A5A;color:#50A0FF;font-weight:bold;")
            self._update_engine_btn(running=False)
            self._log("[ENGINE] Stopped")
        else:
            if not self._engine.strategies:
                QMessageBox.warning(self, "No Strategies", "Add at least one strategy first.")
                return
            self._engine.start()
            self._update_engine_btn(running=True)
            self._log("[ENGINE] Started")

    def _on_signal(self, symbol: str, msg: str, color: str = "#AAAACC"):
        self._log(f'<span style="color:{color}">[{symbol}] {msg}</span>')

    def _on_error(self, strategy, error: str):
        self._log(f'<span style="color:#FF8800">[ERROR] {type(strategy).__name__}: {error}</span>')

    def _log(self, msg: str):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.append(f'<span style="color:#555570">{ts}</span>  {msg}')
