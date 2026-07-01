"""
ui/loading_screen.py

Loading screen shown after TOTP verification.
Runs a StartupWorker that:
  1. Fetches / loads cached instrument list (equity + F&O)
  2. Prefetches holdings, orders, fund summary
  3. Emits ready() when everything is done

Only then does the MainWindow open.
"""
import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar
from PyQt5.QtCore    import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui     import QColor, QPalette, QFont

log = logging.getLogger(__name__)

LOADING_QUOTE = (
    "\"The stock market is a device for transferring money from the impatient to the patient.\"\n"
    "— Warren Buffett\n\n"
    "(Loading your portfolio… please hold your SIPs.)"
)

STEPS = [
    "Authenticating session…",
    "Loading instrument list…",
    "Fetching your holdings…",
    "Fetching order book…",
    "Fetching fund summary…",
    "Almost there…",
]


# ── Startup worker ────────────────────────────────────────────────────────────

class StartupWorker(QThread):
    """
    Runs all pre-launch tasks in a background thread.
    Emits:
      step(int, str)   — progress step index + message
      ready(dict)      — all preloaded data (holdings, orders, funds)
      failed(str)      — fatal error message
    """
    step   = pyqtSignal(int, str)    # (step_index, message)
    ready  = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def run(self):
        result = {}
        try:
            from core.api_client import APIClient
            client = APIClient.get()

            # Step 0 — session already valid (TOTP done)
            self.step.emit(0, STEPS[0])

            # Step 1 — instruments (uses disk cache if available today)
            self.step.emit(1, STEPS[1])
            equity, fno = self._load_instruments(client)
            result["equity"] = equity
            result["fno"]    = fno

            # Step 2 — holdings
            self.step.emit(2, STEPS[2])
            r = client.get_holdings()
            result["holdings"] = self._extract_list(r)

            # Step 3 — orders
            self.step.emit(3, STEPS[3])
            r = client.get_order_book()
            result["orders"] = self._extract_list(r)

            # Step 4 — funds
            self.step.emit(4, STEPS[4])
            r = client.get_fund_summary()
            result["funds"] = r

            # Step 5 — done
            self.step.emit(5, STEPS[5])

            self.ready.emit(result)

        except Exception as e:
            log.error("StartupWorker failed: %s", e, exc_info=True)
            self.failed.emit(str(e))

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _cache_base():
        """Returns the cache/ directory (sibling of ui/, next to the EXE)."""
        import os, sys
        if getattr(sys, "frozen", False):
            app_dir = os.path.dirname(sys.executable)
        else:
            # __file__ is ui/loading_screen.py → go up one level to project root
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cache_dir = os.path.join(app_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    @staticmethod
    def _cache_paths(base, date_str):
        """Three separate cache files — equity is tiny, options are huge."""
        import os
        return {
            "equity":  os.path.join(base, f"eq_{date_str}.json"),
            "fno_fut": os.path.join(base, f"fut_{date_str}.json"),
            "fno_opt": os.path.join(base, f"opt_{date_str}.json"),
        }

    def _load_instruments(self, client) -> tuple:
        """
        Returns (equity_entries, fno_entries) from split cache or API.

        Cache strategy:
          eq_YYYYMMDD.json   — ~2400 equity entries  (~120 KB, loads instantly)
          fut_YYYYMMDD.json  — ~3000 futures          (~150 KB, loads instantly)
          opt_YYYYMMDD.json  — ~146k options          (~5 MB,  NOT loaded at startup)

        F&O list in UI shows futures only by default.
        Options are loaded lazily when user types in the F&O search box.
        """
        import requests as _req, json, os
        from datetime import date

        base = self._cache_base()
        today = date.today().strftime("%Y%m%d")
        paths = self._cache_paths(base, today)

        # Try cache — only equity + futures needed at startup
        if os.path.exists(paths["fno_fut"]):
            try:
                with open(paths["fno_fut"], "r", encoding="utf-8") as f:
                    fut = json.load(f)
                log.info("Instruments: cache hit — %d futures", len(fut))
                return [], fut   # equity removed, futures only
            except Exception as e:
                log.warning("Cache read failed: %s — refetching", e)

        # Fetch from API
        url = "https://api.mstock.trade/openapi/typea/instruments/scriptmaster"
        log.info("Instruments: fetching %s", url)
        resp = _req.get(url, headers=client._auth_headers(), timeout=30)
        resp.raise_for_status()
        csv_text = resp.text
        log.info("Instruments: %d raw lines", len(csv_text.splitlines()))

        equity, fut, opt = self._parse_csv(csv_text)
        log.info("Parsed: %d futures, %d options (equity skipped)", len(fut), len(opt))

        # Delete old cache files, save new split files
        try:
            for fn in os.listdir(base):
                if (fn.startswith(("eq_", "fut_", "opt_")) and
                        fn.endswith(".json") and not fn.endswith(f"{today}.json")):
                    try:
                        os.remove(os.path.join(base, fn))
                    except Exception:
                        pass
            # equity cache removed — futures + options only
            # (equity file no longer written)
            with open(paths["fno_fut"], "w", encoding="utf-8") as f:
                json.dump(fut, f, separators=(",",":"))
            with open(paths["fno_opt"], "w", encoding="utf-8") as f:
                json.dump(opt, f, separators=(",",":"))   # written but not loaded yet
            log.info("Instruments: saved to cache — 2 files (fut + opt)")
        except Exception as e:
            log.warning("Cache write failed: %s", e)

        return [], fut   # equity=[] always

    def _parse_csv(self, csv_text: str) -> tuple:
        """
        Parse scriptmaster CSV. Returns (equity, futures, options).
        Entry format: "EXCHANGE|SYMBOL|Display Name  (SYMBOL)"
        Splits F&O into futures and options so only futures are loaded at startup.
        """
        lines = csv_text.strip().splitlines()
        if len(lines) < 2:
            return [], []
        try:
            header = [h.strip().strip('"').lower() for h in lines[0].split(",")]
            sym_idx  = header.index("tradingsymbol")
            exch_idx = header.index("exchange")
            type_idx = header.index("instrument_type")
            name_idx = header.index("name") if "name" in header else -1
            exp_idx  = header.index("expiry") if "expiry" in header else -1
            log.info("Scriptmaster columns: %s", header[:8])
        except (ValueError, IndexError) as e:
            log.warning("Cannot parse scriptmaster header: %s", e)
            return [], []

        equity, fno = [], []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) <= max(sym_idx, exch_idx, type_idx):
                continue
            exch  = parts[exch_idx].strip().strip('"')
            sym   = parts[sym_idx].strip().strip('"')
            itype = parts[type_idx].strip().strip('"').upper()
            name  = (parts[name_idx].strip().strip('"')
                     if name_idx >= 0 and name_idx < len(parts) else "")
            if not sym or not exch:
                continue

            if exch in ("NSE", "BSE") and itype == "EQ":
                # Filter test/junk symbols
                if (len(sym) < 2 or sym[0].isdigit() or
                        "TEST" in sym.upper() or "DUMMY" in sym.upper()):
                    continue
                if not sym.upper().endswith("-EQ"):
                    sym = sym + "-EQ"
                # Display: "Company Name  (SYMBOL)" or just symbol if no name
                display = f"{name}  ({sym})" if name and name != sym else sym
                equity.append(f"{exch}|{sym}|{display}")

            elif exch in ("NFO", "BFO") and itype in ("FUT", "CE", "PE"):
                expiry = (parts[exp_idx].strip().strip('"')
                          if exp_idx >= 0 and exp_idx < len(parts) else "")
                # Format expiry: "2026-06-26" → "Jun 26"
                exp_short = ""
                if expiry:
                    try:
                        from datetime import datetime
                        dt = datetime.strptime(expiry, "%Y-%m-%d")
                        exp_short = dt.strftime("%b %y")   # "Jun 26"
                    except Exception:
                        exp_short = expiry

                # Use company name from CSV if available
                underlying = name.strip() if name and name.upper() != sym.upper() else ""

                if itype == "FUT":
                    # "Company Name — Jun 26 FUT" or "SYMBOL — Jun 26 FUT"
                    label = underlying or sym.replace("FUT", "").rstrip()
                    display = f"{label} — {exp_short} FUT" if exp_short else f"{label} FUT"
                else:
                    # Options: keep compact "SYMBOL  EXPIRY" — too many to name individually
                    display = f"{sym}  {expiry}".strip() if expiry else sym

                fno.append(f"{exch}|{sym}|{display}")

        # Deduplicate equity — NSE preferred over BSE for same symbol
        seen, eq_deduped = set(), []
        for e in sorted(equity, key=lambda x: (x.split("|")[0] != "NSE", x.split("|")[1])):
            s = e.split("|")[1]
            if s not in seen:
                seen.add(s)
                eq_deduped.append(e)
        eq_deduped.sort(key=lambda x: x.split("|")[2])  # sort by display name

        # Split F&O: futures (~3k) vs options (~146k) — returned separately
        fut = sorted([r for r in fno if r.split("|")[1].endswith("FUT")])
        opt = sorted([r for r in fno if not r.split("|")[1].endswith("FUT")])
        return eq_deduped, fut, opt

    def _extract_list(self, result: dict) -> list:
        data = result.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("data", "orders", "holdings"):
                v = data.get(k)
                if isinstance(v, list):
                    return v
        return []


# ── Loading Screen UI ─────────────────────────────────────────────────────────

class LoadingScreen(QWidget):
    """
    Full-screen loading UI shown between TOTP success and dashboard open.
    Starts StartupWorker automatically on show.
    """
    launch_ready = pyqtSignal(dict)   # emitted with preloaded data

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("background-color:#0A0A14;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(60, 0, 60, 40)
        lay.setSpacing(0)
        lay.addStretch(2)

        # Logo / title
        logo = QLabel("📈  Super Trader")
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            "color:#FFFFFF;font-size:42px;font-weight:bold;"
            "letter-spacing:2px;font-family:'Segoe UI',Arial;"
        )
        lay.addWidget(logo)

        # Subtitle
        sub = QLabel("Powered by mStock Trading API")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(
            "color:#555570;font-size:16px;margin-top:6px;"
            "font-family:'Segoe UI',Arial;"
        )
        lay.addWidget(sub)

        lay.addStretch(1)

        # Quote
        quote = QLabel(LOADING_QUOTE)
        quote.setAlignment(Qt.AlignCenter)
        quote.setWordWrap(True)
        quote.setStyleSheet(
            "color:#4A5580;font-size:16px;font-style:italic;"
            "font-family:'Segoe UI',Arial;line-height:1.6;"
            "padding:0 40px;"
        )
        lay.addWidget(quote)

        lay.addStretch(1)

        # Progress bar
        self._bar = QProgressBar()
        self._bar.setRange(0, len(STEPS) - 1)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            "QProgressBar{background:#1C1C2A;border-radius:3px;border:none;}"
            "QProgressBar::chunk{background:qlineargradient("
            "x1:0,y1:0,x2:1,y2:0,stop:0 #3060C8,stop:1 #50A0FF);"
            "border-radius:3px;}"
        )
        lay.addWidget(self._bar)

        # Step label
        self._step_lbl = QLabel(STEPS[0])
        self._step_lbl.setAlignment(Qt.AlignCenter)
        self._step_lbl.setStyleSheet(
            "color:#5070A0;font-size:16px;margin-top:10px;"
            "font-family:'Segoe UI',Arial;"
        )
        lay.addWidget(self._step_lbl)

        # Version
        ver = QLabel("v1.0.0")
        ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet("color:#252538;font-size:16px;margin-top:20px;")
        lay.addWidget(ver)

    def start(self):
        """Call after show() to begin startup tasks."""
        self._worker = StartupWorker()
        self._worker.step.connect(self._on_step)
        self._worker.ready.connect(self._on_ready)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_step(self, idx: int, msg: str):
        self._bar.setValue(idx)
        self._step_lbl.setText(msg)

    def _on_ready(self, data: dict):
        self._bar.setValue(len(STEPS) - 1)
        self._step_lbl.setText("Ready!")
        # Small delay so user sees 100% before dashboard opens
        QTimer.singleShot(400, lambda: self.launch_ready.emit(data))

    def _on_failed(self, error: str):
        from PyQt5.QtWidgets import QMessageBox
        self._step_lbl.setText(f"Startup failed: {error}")
        self._step_lbl.setStyleSheet("color:#FF6060;font-size:16px;margin-top:10px;")
        QMessageBox.critical(
            self, "Startup Failed",
            f"Could not load data:\n\n{error}\n\n"
            "Please check your internet connection and try again."
        )
