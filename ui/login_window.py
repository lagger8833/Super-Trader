"""
ui/login_window.py - Login screen, maximized, simple API key found/not found badge.
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from core.api_client import APIClient
from core.auth_manager import load_credentials, save_credentials
from core.env_loader import load_env_config, get_env_file_path

STYLE = """
QMainWindow, QWidget { background-color: #12121C; color: #DCDCE6; }
QFrame#card { background-color: #1C1C2A; border: 1px solid #2A2A40; border-radius: 12px; }
QLabel#title  { color: #FFFFFF; font-size: 26px; font-weight: bold; }
QLabel#sub    { color: #888899; font-size: 13px; }
QLabel#flabel { color: #AAAACC; font-size: 12px; font-weight: bold; }
QLineEdit {
    background-color: #252538; border: 1px solid #353550; border-radius: 6px;
    padding: 10px 14px; color: #DCDCE6; font-size: 14px; min-height: 20px;
}
QLineEdit:focus { border: 1px solid #5078DC; }
QPushButton#login_btn {
    background-color: #4060C8; color: #FFFFFF; border: none;
    border-radius: 6px; font-size: 15px; font-weight: bold; min-height: 44px;
}
QPushButton#login_btn:hover    { background-color: #5070D8; }
QPushButton#login_btn:disabled { background-color: #303048; color: #666680; }
QCheckBox { color: #888899; font-size: 12px; }
"""


class LoginWorker(QThread):
    success = pyqtSignal(dict)
    failure = pyqtSignal(str)

    def __init__(self, user_id, password):
        super().__init__()
        self.user_id  = user_id
        self.password = password

    def run(self):
        r = APIClient.get().login(self.user_id, self.password)
        if r["success"]:
            self.success.emit(r)
        else:
            self.failure.emit(r.get("error", "Login failed"))


class LoginWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("mStock Trader — Login")
        self.setMinimumSize(500, 550)
        self.setStyleSheet(STYLE)
        self._api_key  = ""
        self._checksum = "L"
        self._build_ui()
        self._load_env()
        self._prefill_saved()
        self.showMaximized()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setAlignment(Qt.AlignCenter)
        outer.setContentsMargins(20, 20, 20, 20)

        card = QFrame(objectName="card")
        card.setFixedWidth(460)
        lay = QVBoxLayout(card)
        lay.setSpacing(14)
        lay.setContentsMargins(40, 36, 40, 36)

        # Title
        t = QLabel("📈 Super Trader", objectName="title")
        t.setAlignment(Qt.AlignCenter)
        s = QLabel("Powered by mStock Trading API and LaggeR", objectName="sub")
        s.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        lay.addWidget(s)
        lay.addSpacing(6)

        # ── API key status badge (Fix #4: just found / not found) ──
        self.key_badge = QLabel("")
        self.key_badge.setAlignment(Qt.AlignCenter)
        self.key_badge.setFixedHeight(36)
        self.key_badge.setWordWrap(False)
        lay.addWidget(self.key_badge)
        lay.addSpacing(4)

        # Fields
        lay.addWidget(QLabel("USER ID", objectName="flabel"))
        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText("Enter your mStock User ID")
        self.user_id_input.setMinimumHeight(44)
        lay.addWidget(self.user_id_input)

        lay.addWidget(QLabel("PASSWORD", objectName="flabel"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Enter your password")
        self.password_input.setMinimumHeight(44)
        self.password_input.returnPressed.connect(self._on_login)
        lay.addWidget(self.password_input)

        self.remember_cb = QCheckBox("Remember credentials (encrypted)")
        lay.addWidget(self.remember_cb)

        self.login_btn = QPushButton("Login", objectName="login_btn")
        self.login_btn.setEnabled(False)
        self.login_btn.clicked.connect(self._on_login)
        lay.addSpacing(4)
        lay.addWidget(self.login_btn)

        self.status_lbl = QLabel("")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("color:#FF6666;font-size:12px;")
        lay.addWidget(self.status_lbl)

        outer.addWidget(card)

    def _load_env(self):
        """Fix #4: just show ✓ API Key Found or ✗ API Key Not Found."""
        try:
            api_key, checksum, _ = load_env_config()
            self._api_key  = api_key
            self._checksum = checksum
            self.key_badge.setText("✓  API Key Found")
            self.key_badge.setStyleSheet(
                "color:#40CC70; font-size:13px; font-weight:bold;"
                "background:#0F2A1A; border:1px solid #1A5A30; border-radius:4px; padding:4px 12px;"
            )
            self.login_btn.setEnabled(True)
        except (FileNotFoundError, KeyError):
            self._api_key  = ""
            self._checksum = "L"
            env_path = get_env_file_path()
            self.key_badge.setText(f"✗  API Key Not Found  —  add API_KEY to: {env_path}")
            self.key_badge.setStyleSheet(
                "color:#FF6666; font-size:12px;"
                "background:#2A0F0F; border:1px solid #5A2020; border-radius:4px; padding:4px 12px;"
            )
            self.key_badge.setFixedHeight(48)
            self.key_badge.setWordWrap(True)
            self.login_btn.setEnabled(False)

    def _prefill_saved(self):
        creds = load_credentials()
        if creds:
            self.user_id_input.setText(creds.get("user_id", ""))
            self.password_input.setText(creds.get("password", ""))
            self.remember_cb.setChecked(True)

    def _on_login(self):
        if not self._api_key:
            self.status_lbl.setText("API Key not found — check your .env file")
            return
        uid = self.user_id_input.text().strip()
        pwd = self.password_input.text().strip()
        if not uid or not pwd:
            self.status_lbl.setText("User ID and Password are required")
            return

        self.login_btn.setEnabled(False)
        self.login_btn.setText("Logging in…")
        self.status_lbl.setText("")
        client = APIClient.get()
        client._api_key  = self._api_key
        client._checksum = self._checksum

        self._worker = LoginWorker(uid, pwd)
        self._worker.success.connect(lambda _: self._on_success(uid, pwd))
        self._worker.failure.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, uid, pwd):
        if self.remember_cb.isChecked():
            save_credentials(uid, pwd)
        self.login_btn.setEnabled(True)
        self.login_btn.setText("Login")
        from ui.totp_window import TOTPWindow
        self._next = TOTPWindow(uid, pwd, self._api_key)
        self._next.showMaximized()
        self.close()

    def _on_failure(self, error: str):
        self.login_btn.setEnabled(True)
        self.login_btn.setText("Login")
        self.status_lbl.setText(f"✗  {error}")
