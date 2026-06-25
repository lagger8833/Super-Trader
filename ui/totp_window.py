"""
ui/totp_window.py
Verify screen — maximized, larger inputs, Resend OTP button.
Handles both SMS OTP (Path A) and Authenticator TOTP (Path B).
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QMessageBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer

from core.api_client import APIClient
from core.auth_manager import update_access_token


STYLE = """
QMainWindow, QWidget { background-color: #12121C; color: #DCDCE6; }
QFrame#card {
    background-color: #1C1C2A; border: 1px solid #2A2A40; border-radius: 12px;
}
QLabel#title { color: #FFFFFF; font-size: 24px; font-weight: bold; }
QLabel#subtitle { color: #888899; font-size: 13px; }
QLabel#field_label { color: #AAAACC; font-size: 12px; font-weight: bold; }
QLabel#hint { color: #555570; font-size: 12px; }
/* FIX #2: large padding + min-height so digits never clip */
QLineEdit#code_input {
    background-color: #252538; border: 2px solid #353550; border-radius: 8px;
    padding: 14px 16px; color: #DCDCE6;
    font-size: 28px; letter-spacing: 10px;
    min-height: 52px;
    qproperty-alignment: AlignCenter;
}
QLineEdit#code_input:focus { border: 2px solid #5078DC; }
QPushButton#verify_btn {
    background-color: #20A060; color: #FFFFFF; border: none;
    border-radius: 6px; padding: 12px; font-size: 15px; font-weight: bold;
    min-height: 46px;
}
QPushButton#verify_btn:hover    { background-color: #28B870; }
QPushButton#verify_btn:disabled { background-color: #183030; color: #446650; }
QPushButton#mode_btn {
    background-color: #252538; color: #888899;
    border: 1px solid #353550; border-radius: 4px;
    padding: 8px 16px; font-size: 13px; min-height: 36px;
}
QPushButton#mode_btn:checked {
    background-color: #1A3A5A; color: #50A0FF;
    border-color: #2A5070; font-weight: bold;
}
QPushButton#resend_btn {
    background-color: #252538; color: #AAAACC;
    border: 1px solid #353550; border-radius: 4px;
    padding: 8px 16px; font-size: 12px; min-height: 36px;
}
QPushButton#resend_btn:hover    { background-color: #303048; color: #FFFFFF; }
QPushButton#resend_btn:disabled { color: #555570; background-color: #1C1C2A; border-color: #252538; }
QPushButton#back_btn {
    background-color: transparent; color: #888899; border: none;
    font-size: 12px; text-decoration: underline; min-height: 30px;
}
QPushButton#back_btn:hover { color: #AAAACC; }
"""

RESEND_COOLDOWN = 30   # seconds before Resend OTP is re-enabled


class LoginWorker(QThread):
    """Re-runs login() to trigger a fresh OTP."""
    success = pyqtSignal()
    failure = pyqtSignal(str)

    def __init__(self, user_id, password):
        super().__init__()
        self.user_id = user_id
        self.password = password

    def run(self):
        result = APIClient.get().login(self.user_id, self.password)
        if result["success"]:
            self.success.emit()
        else:
            self.failure.emit(result.get("error", "Resend failed"))


class VerifyWorker(QThread):
    success = pyqtSignal(dict)
    failure = pyqtSignal(str)

    def __init__(self, mode: str, code: str):
        super().__init__()
        self.mode = mode
        self.code = code

    def run(self):
        client = APIClient.get()
        result = (
            client.generate_session(self.code)
            if self.mode == "otp"
            else client.verify_totp(self.code)
        )
        if result["success"]:
            self.success.emit(result)
        else:
            self.failure.emit(result.get("error", "Verification failed"))


class TOTPWindow(QMainWindow):
    def __init__(self, user_id: str, password: str, api_key: str):
        super().__init__()
        self.user_id   = user_id
        self.password  = password
        self.api_key   = api_key
        self._mode     = "totp"
        self._resend_seconds = 0
        self._resend_timer   = QTimer(self)
        self._resend_timer.timeout.connect(self._tick_resend)

        self.setWindowTitle("Super Trader — Verify")
        self.setMinimumSize(500, 520)
        self.setStyleSheet(STYLE)
        self._build_ui()
        # FIX #3: maximized on open (called by login_window via showMaximized)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setAlignment(Qt.AlignCenter)
        outer.setContentsMargins(20, 20, 20, 20)

        card = QFrame(objectName="card")
        card.setFixedWidth(500)
        layout = QVBoxLayout(card)
        layout.setSpacing(16)
        layout.setContentsMargins(40, 36, 40, 36)

        # Icon + title
        icon_lbl = QLabel("🔐")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 36px;")
        layout.addWidget(icon_lbl)

        title = QLabel("Verify Identity", objectName="title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Mode toggle — TOTP is default, SMS OTP is a small fallback link
        self.sms_fallback_btn = QPushButton("Don't have TOTP? Use SMS OTP instead",
                                            objectName="back_btn")
        self.sms_fallback_btn.clicked.connect(lambda: self._set_mode("otp"))
        layout.addWidget(self.sms_fallback_btn)

        self.totp_fallback_btn = QPushButton("← Back to Authenticator TOTP",
                                             objectName="back_btn")
        self.totp_fallback_btn.clicked.connect(lambda: self._set_mode("totp"))
        self.totp_fallback_btn.setVisible(False)
        layout.addWidget(self.totp_fallback_btn)

        # Hidden — kept for _set_mode compatibility
        self.otp_btn  = QPushButton(objectName="mode_btn")
        self.otp_btn.setVisible(False)
        self.totp_btn = QPushButton(objectName="mode_btn")
        self.totp_btn.setVisible(False)

        # Description
        self.desc_lbl = QLabel("", objectName="subtitle")
        self.desc_lbl.setAlignment(Qt.AlignCenter)
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setMinimumHeight(36)
        layout.addWidget(self.desc_lbl)

        # Code input — FIX #2: named so CSS min-height applies
        layout.addWidget(QLabel("6-DIGIT CODE", objectName="field_label"))
        self.code_input = QLineEdit()
        self.code_input.setObjectName("code_input")
        self.code_input.setPlaceholderText("0  0  0  0  0  0")
        self.code_input.setMaxLength(6)
        self.code_input.setAlignment(Qt.AlignCenter)
        self.code_input.returnPressed.connect(self._verify)
        layout.addWidget(self.code_input)

        # Hint + Resend row — FIX #4
        hint_row = QHBoxLayout()
        self.hint_lbl = QLabel("", objectName="hint")
        self.hint_lbl.setWordWrap(True)
        hint_row.addWidget(self.hint_lbl, 1)

        self.resend_btn = QPushButton("Resend OTP", objectName="resend_btn")
        self.resend_btn.setVisible(False)   # only shown in OTP mode
        self.resend_btn.clicked.connect(self._resend_otp)
        hint_row.addWidget(self.resend_btn)
        layout.addLayout(hint_row)

        # Verify button
        self.verify_btn = QPushButton("Verify & Continue", objectName="verify_btn")
        self.verify_btn.clicked.connect(self._verify)
        layout.addWidget(self.verify_btn)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#FF6666;font-size:13px;min-height:20px;")
        layout.addWidget(self.status_label)

        back_btn = QPushButton("← Back to Login", objectName="back_btn")
        back_btn.clicked.connect(self._back)
        layout.addWidget(back_btn)

        outer.addWidget(card)

        self._set_mode("totp")
        self.code_input.setFocus()

    # ── Mode toggle ────────────────────────────────────────────

    def _set_mode(self, mode: str):
        self._mode = mode
        self.resend_btn.setVisible(mode == "otp")
        self.sms_fallback_btn.setVisible(mode == "totp")
        self.totp_fallback_btn.setVisible(mode == "otp")
        self.code_input.clear()
        self.status_label.setText("")

        if mode == "otp":
            self.desc_lbl.setText(
                "Enter the OTP sent to your registered mobile number after login."
            )
            self.hint_lbl.setText("Didn't receive it? Click Resend OTP below.")
            if self._resend_seconds == 0:
                self._start_resend_cooldown()
        else:
            self.desc_lbl.setText(
                "Enter the 6-digit code from your authenticator app\n"
                "(Google Authenticator, Authy, etc.)"
            )
            self.hint_lbl.setText("Code refreshes every 30 seconds")
            self._resend_timer.stop()

    # ── Resend OTP (FIX #4) ────────────────────────────────────

    def _start_resend_cooldown(self):
        """Disable Resend for RESEND_COOLDOWN seconds, then re-enable."""
        self._resend_seconds = RESEND_COOLDOWN
        self.resend_btn.setEnabled(False)
        self.resend_btn.setText(f"Resend OTP ({self._resend_seconds}s)")
        self._resend_timer.start(1000)

    def _tick_resend(self):
        self._resend_seconds -= 1
        if self._resend_seconds <= 0:
            self._resend_timer.stop()
            self.resend_btn.setEnabled(True)
            self.resend_btn.setText("Resend OTP")
        else:
            self.resend_btn.setText(f"Resend OTP ({self._resend_seconds}s)")

    def _resend_otp(self):
        self.resend_btn.setEnabled(False)
        self.resend_btn.setText("Sending…")
        self.status_label.setText("")
        self.code_input.clear()

        self._resend_worker = LoginWorker(self.user_id, self.password)
        self._resend_worker.success.connect(self._on_resend_ok)
        self._resend_worker.failure.connect(self._on_resend_fail)
        self._resend_worker.start()

    def _on_resend_ok(self):
        self.status_label.setStyleSheet("color:#40CC70;font-size:13px;")
        self.status_label.setText("✓ OTP sent — check your mobile")
        self._start_resend_cooldown()
        self.code_input.setFocus()

    def _on_resend_fail(self, error: str):
        self.status_label.setStyleSheet("color:#FF6666;font-size:13px;")
        self.status_label.setText(f"✗ Resend failed: {error}")
        self.resend_btn.setEnabled(True)
        self.resend_btn.setText("Resend OTP")

    # ── Verify ─────────────────────────────────────────────────

    def _verify(self):
        code = self.code_input.text().strip()
        if len(code) != 6 or not code.isdigit():
            self.status_label.setStyleSheet("color:#FF6666;font-size:13px;")
            self.status_label.setText("⚠ Enter a valid 6-digit code")
            return

        self.verify_btn.setEnabled(False)
        self.verify_btn.setText("Verifying…")
        self.status_label.setText("")

        self._worker = VerifyWorker(self._mode, code)
        self._worker.success.connect(self._on_success)
        self._worker.failure.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, result: dict):
        token = result.get("access_token", "") or (result.get("data") or {}).get("access_token", "")

        # Guard: never open the dashboard without a valid token
        if not token:
            self._on_failure(
                "Authentication appeared to succeed but no session token was received. "
                "Please try again."
            )
            return

        update_access_token(token)
        self._resend_timer.stop()
        self.verify_btn.setEnabled(True)
        self.verify_btn.setText("Verify & Continue")

        from ui.main_window import MainWindow
        self._main = MainWindow()
        self._main.showMaximized()
        self.close()

    def _on_failure(self, error: str):
        self.verify_btn.setEnabled(True)
        self.verify_btn.setText("Verify & Continue")
        self.code_input.clear()
        self.code_input.setFocus()

        # IP whitelist error — show dedicated popup
        if "ip address" in error.lower() or (
                "ip" in error.lower() and "match" in error.lower()):
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
                f"<b>mStock blocked this request:</b><br>"
                f"{error}<br><br>"
                f"<b>Your current public IP:</b><br>"
                f"<code style='font-size:14px;'>{current_ip}</code><br><br>"
                f"<b>Steps to fix:</b><br>"
                f"1. Go to <b>trade.mstock.com</b><br>"
                f"2. Menu → Products → <b>Trading APIs</b><br>"
                f"3. Click <b>API Settings</b><br>"
                f"4. Add <b>{current_ip}</b> as Primary or Secondary IP<br>"
                f"5. Save, then try again<br><br>"
                f"<i>There is no API to update this automatically.<br>"
                f"Contact mStock support if the issue persists:<br>"
                f"<b>tradingapi@mstock.com</b></i>",
            )
            self.status_label.setStyleSheet("color:#FF8800;font-size:12px;")
            self.status_label.setText("⚠ IP not whitelisted — see popup for steps")
        else:
            self.status_label.setStyleSheet("color:#FF6666;font-size:13px;")
            self.status_label.setText(f"✗ {error}")

    def _back(self):
        self._resend_timer.stop()
        from ui.login_window import LoginWindow
        self._login = LoginWindow()
        self._login.showMaximized()
        self.close()

    def closeEvent(self, event):
        self._resend_timer.stop()
        event.accept()
