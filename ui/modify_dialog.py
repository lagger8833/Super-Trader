"""
ui/modify_dialog.py
Dialogs for modifying open orders and holdings (sell with custom qty/price).
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QDoubleSpinBox,
    QSpinBox, QComboBox, QDialogButtonBox, QMessageBox
)
from PyQt5.QtCore import Qt
from core.api_client import APIClient

DIALOG_STYLE = """
QDialog { background-color: #1C1C2A; color: #DCDCE6; }
QLabel { color: #AAAACC; }
QLabel.title { color: #FFFFFF; font-size: 14px; font-weight: bold; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #252538; border: 1px solid #353550;
    border-radius: 4px; padding: 6px; color: #DCDCE6;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #5078DC; }
QPushButton {
    background-color: #252538; color: #DCDCE6;
    border: 1px solid #353550; border-radius: 4px; padding: 6px 16px;
}
QPushButton:hover { background-color: #303048; }
QPushButton#confirm_btn {
    background-color: #4060C8; color: #FFFFFF; border-color: #5070D8;
}
QPushButton#confirm_btn:hover { background-color: #5070D8; }
"""


class ModifyOrderDialog(QDialog):
    """Modify an existing open order."""

    def __init__(self, order: dict, parent=None):
        super().__init__(parent)
        self.order = order
        self.order_id = order.get("order_id", "")
        self.setWindowTitle("Modify Order")
        self.setMinimumWidth(380)
        self.setStyleSheet(DIALOG_STYLE)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        symbol = self.order.get("tradingsymbol") or self.order.get("symbol", "")
        title = QLabel(f"Modify Order — {symbol}", objectName="title")
        title.setStyleSheet("color:#FFF;font-size:14px;font-weight:bold;")
        layout.addWidget(title)

        sub = QLabel(f"Order ID: {self.order_id}")
        sub.setStyleSheet("color:#555570;font-size:11px;")
        layout.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(10)

        self.order_type_combo = QComboBox()
        self.order_type_combo.addItems(["MARKET", "LIMIT", "SL", "SL-M"])
        current_type = self.order.get("order_type", "MARKET")
        idx = self.order_type_combo.findText(current_type)
        if idx >= 0:
            self.order_type_combo.setCurrentIndex(idx)
        form.addRow("Order Type:", self.order_type_combo)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 1000000)
        self.qty_spin.setValue(int(self.order.get("quantity", 1)))
        form.addRow("Quantity:", self.qty_spin)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 1e7)
        self.price_spin.setDecimals(2)
        self.price_spin.setPrefix("₹ ")
        self.price_spin.setValue(float(self.order.get("price", 0)))
        form.addRow("Price:", self.price_spin)

        self.trigger_spin = QDoubleSpinBox()
        self.trigger_spin.setRange(0, 1e7)
        self.trigger_spin.setDecimals(2)
        self.trigger_spin.setPrefix("₹ ")
        self.trigger_spin.setValue(float(self.order.get("trigger_price", 0)))
        form.addRow("Trigger Price:", self.trigger_spin)

        self.validity_combo = QComboBox()
        self.validity_combo.addItems(["DAY", "IOC"])
        form.addRow("Validity:", self.validity_combo)

        layout.addLayout(form)

        # Buttons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = QPushButton("Modify Order", objectName="confirm_btn")
        confirm_btn.clicked.connect(self._submit)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(confirm_btn)
        layout.addLayout(btn_layout)

    def _submit(self):
        result = APIClient.get().modify_order(
            order_id=self.order_id,
            order_type=self.order_type_combo.currentText(),
            quantity=str(self.qty_spin.value()),
            price=str(self.price_spin.value()),
            validity=self.validity_combo.currentText(),
            trigger_price=str(self.trigger_spin.value()),
        )
        if result["success"]:
            QMessageBox.information(self, "Success", "Order modified successfully")
            self.accept()
        else:
            QMessageBox.warning(self, "Error",
                                result.get("error", "Modification failed"))


class ModifyHoldingDialog(QDialog):
    """Place a sell order for a holding with custom parameters."""

    def __init__(self, holding: dict, parent=None):
        super().__init__(parent)
        self.holding = holding
        symbol = holding.get("tradingsymbol") or holding.get("symbol", "")
        self.setWindowTitle(f"Sell / Modify Holding — {symbol}")
        self.setMinimumWidth(380)
        self.setStyleSheet(DIALOG_STYLE)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        symbol   = self.holding.get("tradingsymbol") or self.holding.get("symbol", "")
        exchange = self.holding.get("exchange", "NSE")
        qty      = int(self.holding.get("quantity") or self.holding.get("qty", 1))
        avg      = float(self.holding.get("average_price") or self.holding.get("avg_price", 0))
        product  = self.holding.get("product", "CNC")

        title = QLabel(f"Sell {symbol} — {exchange}")
        title.setStyleSheet("color:#FFF;font-size:14px;font-weight:bold;")
        layout.addWidget(title)

        info = QLabel(f"Avg Price: ₹{avg:,.2f}  |  Available Qty: {qty}  |  Product: {product}")
        info.setStyleSheet("color:#666680;font-size:11px;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)

        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, qty)
        self.qty_spin.setValue(qty)
        form.addRow("Sell Quantity:", self.qty_spin)

        self.order_type_combo = QComboBox()
        self.order_type_combo.addItems(["MARKET", "LIMIT", "SL", "SL-M"])
        self.order_type_combo.currentTextChanged.connect(self._toggle_price)
        form.addRow("Order Type:", self.order_type_combo)

        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0, 1e7)
        self.price_spin.setDecimals(2)
        self.price_spin.setPrefix("₹ ")
        self.price_spin.setValue(avg)
        form.addRow("Limit Price:", self.price_spin)

        self.trigger_spin = QDoubleSpinBox()
        self.trigger_spin.setRange(0, 1e7)
        self.trigger_spin.setDecimals(2)
        self.trigger_spin.setPrefix("₹ ")
        form.addRow("Trigger Price:", self.trigger_spin)

        self.validity_combo = QComboBox()
        self.validity_combo.addItems(["DAY", "IOC"])
        form.addRow("Validity:", self.validity_combo)

        layout.addLayout(form)
        self._toggle_price("MARKET")

        # Buttons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        sell_btn = QPushButton("Place Sell Order", objectName="confirm_btn")
        sell_btn.setStyleSheet(
            "background:#5A1A1A;color:#FF6060;border-color:#703030;font-weight:bold;")
        sell_btn.clicked.connect(self._submit)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(sell_btn)
        layout.addLayout(btn_layout)

        self._symbol   = symbol
        self._exchange = exchange
        self._product  = product

    def _toggle_price(self, order_type: str):
        need_price   = order_type in ("LIMIT", "SL")
        need_trigger = order_type in ("SL", "SL-M")
        self.price_spin.setEnabled(need_price)
        self.trigger_spin.setEnabled(need_trigger)

    def _submit(self):
        result = APIClient.get().place_order(
            variety="regular",
            symbol=self._symbol,
            exchange=self._exchange,
            transaction_type="SELL",
            order_type=self.order_type_combo.currentText(),
            quantity=str(self.qty_spin.value()),
            product=self._product,
            validity=self.validity_combo.currentText(),
            price=str(self.price_spin.value()),
            trigger_price=str(self.trigger_spin.value()),
            disclosed_quantity="0",
            tag="",
        )
        if result["success"]:
            QMessageBox.information(self, "Success",
                                    f"Sell order placed for {self._symbol}")
            self.accept()
        else:
            QMessageBox.warning(self, "Error",
                                result.get("error", "Order failed"))
