# Super Trader — Desktop Trading Platform

A full-featured desktop trading platform built on the **mStock Trading API (Type A)**,
packaged as a standalone Windows EXE.

---

## Features

| Feature | Details |
|---|---|
| 🔐 Secure Login | Username + Password + TOTP (2FA) |
| 🔒 Encrypted Storage | Credentials encrypted with Fernet (AES-128) + PBKDF2 |
| 📊 Holdings Dashboard | Live P&L, current value, per-holding sell/modify |
| 📋 Order Book | Status-coloured orders, cancel, modify |
| 🤖 Algo Engine | 3 built-in strategies, background execution |
| ➕ Manual Orders | Full order form: MARKET/LIMIT/SL/SL-M, CNC/MIS/NRML |
| 🔄 Auto Refresh | Every 60 seconds |

---

## Quick Start (Development)

```bash
# 1. Clone / download the project
cd super_trader

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python main.py
```

---

## Building the EXE (Windows)

```cmd
build_windows.bat
```

This will:
1. Upgrade pip/setuptools
2. Install all dependencies
3. Build `dist\SuperTrader.exe` — a single portable executable

---

## Authentication Flow

```
Login Screen
  → Enter: User ID, Password, API Key
  → [Login]
      ↓
TOTP Screen
  → Enter 6-digit authenticator code
  → [Verify & Continue]
      ↓
Main Dashboard
```

Credentials are stored **encrypted** in `~/.super_trader/credentials.enc`
using a machine-unique key derived via PBKDF2-HMAC-SHA256.

---

## Algo Engine Strategies

### 1. Moving Average Crossover
- Buys when short MA crosses above long MA
- Sells when short MA crosses below long MA
- Configurable: short window, long window

### 2. RSI Overbought/Oversold
- Buys when RSI falls below oversold level
- Sells when RSI rises above overbought level
- Configurable: period, overbought level, oversold level

### 3. Price Level Trigger
- Buys when LTP ≤ your buy price
- Sells when LTP ≥ your sell price
- Configurable: buy price, sell price

**To add your own strategy:**
```python
# algo/engine.py
class MyStrategy(BaseStrategy):
    def evaluate(self) -> Optional[str]:
        ltp = self.get_ltp()
        # your logic here
        if ltp < 100:
            return "BUY"
        return None
```
Then register it in `STRATEGY_MAP` inside `ui/algo_panel.py`.

---

## Project Structure

```
mstock_trader/
├── main.py                  # Entry point
├── requirements.txt
├── super_trader.spec       # PyInstaller config
├── build_windows.bat        # One-click build script
├── core/
│   ├── api_client.py        # MConnect wrapper
│   └── auth_manager.py      # Encrypted credential storage
├── algo/
│   └── engine.py            # Algorithmic trading engine + strategies
└── ui/
    ├── login_window.py      # Login screen
    ├── totp_window.py       # TOTP verification screen
    ├── main_window.py       # Main dashboard
    ├── algo_panel.py        # Algo engine UI
    ├── order_panel.py       # Manual order placement
    └── modify_dialog.py     # Modify order/holding dialogs
```

---

## API Keys

Obtain your API key from the mStock developer portal.
You'll need: **User ID**, **Password**, **API Key**.

---

## Security Notes

- Credentials are encrypted with Fernet symmetric encryption
- The encryption key is derived from your machine identity (hostname + username)
  using PBKDF2-HMAC-SHA256 with 480,000 iterations
- No credentials are transmitted anywhere other than the mStock API
- Use "Logout" to clear the session (does NOT delete saved credentials)
- To fully clear saved credentials, delete `~/.super_trader/`
