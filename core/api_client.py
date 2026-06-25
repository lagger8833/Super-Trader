"""
core/api_client.py
Wrapper around tradingapi_a.MConnect.

Auth flow — two paths:
  PATH A (OTP):   login() → generate_session(otp)  → access_token
  PATH B (TOTP):  login() → verify_totp(totp)       → access_token

Every method checks BOTH the exception layer AND the response body
status field, so a body-level {"status":"error"} always surfaces as
{"success": False, "error": <message>} and never silently passes.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _parse_response(resp) -> dict:
    """Safely extract JSON dict from an SDK response object."""
    try:
        if hasattr(resp, "json"):
            return resp.json()
        if isinstance(resp, dict):
            return resp
    except Exception:
        pass
    return {}


def _check_body_error(data: dict) -> Optional[str]:
    """
    Return an error string if the response body signals failure,
    even when the HTTP status was 200.
    Returns None if response looks successful.
    """
    status = str(data.get("status", "")).lower()
    if status == "error":
        return (
            data.get("message")
            or data.get("error")
            or "API returned an error"
        )
    return None


class APIClient:
    _instance: Optional["APIClient"] = None

    def __init__(self):
        self._mconnect  = None
        self._logged_in = False
        self._api_key   = ""
        self._checksum  = "L"
        self._access_token = ""
        self._user_id   = ""

    @classmethod
    def get(cls) -> "APIClient":
        if cls._instance is None:
            cls._instance = APIClient()
        return cls._instance

    def _init_mconnect(self):
        from tradingapi_a.mconnect import MConnect
        self._mconnect = MConnect()

    # ── Auth Step 1 ────────────────────────────────────────────

    def login(self, user_id: str, password: str) -> dict:
        """
        Step 1 (both paths): username + password.
        Success triggers an SMS OTP (if TOTP not enabled).
        """
        self._init_mconnect()
        self._user_id = user_id
        try:
            resp = self._mconnect.login(user_id, password)
            data = _parse_response(resp)
            logger.info("Login response: %s", data)

            # Check body-level error (e.g. wrong password returns status:"error")
            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}

            return {"success": True, "data": data}
        except Exception as e:
            logger.error("Login failed: %s", e)
            return {"success": False, "error": str(e)}

    # ── Auth Step 2 — Path A (OTP) ────────────────────────────

    def generate_session(self, otp: str) -> dict:
        """
        Exchange the SMS OTP for an access_token.
        request_token = OTP, checksum = "L" (per official docs).
        """
        try:
            resp = self._mconnect.generate_session(
                self._api_key, otp, self._checksum
            )
            data = _parse_response(resp)
            logger.info("generate_session response: %s", data)

            # Check body-level error first (wrong/expired OTP, bad API key, etc.)
            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}

            # Extract access_token — required for all subsequent calls
            token = (
                data.get("access_token")
                or (data.get("data") or {}).get("access_token", "")
            )
            if not token:
                return {
                    "success": False,
                    "error": "Authentication succeeded but no access token was returned. "
                             "Please try again or contact mStock support."
                }

            self._access_token = token
            self._logged_in    = True
            logger.info("Session via OTP OK, token: %s…", token[:12])
            return {"success": True, "data": data, "access_token": token}

        except Exception as e:
            logger.error("generate_session failed: %s", e)
            return {"success": False, "error": str(e)}

    # ── Auth Step 2 — Path B (TOTP) ───────────────────────────

    def verify_totp(self, totp: str) -> dict:
        """Verify 6-digit authenticator TOTP and obtain access_token."""
        try:
            resp = self._mconnect.verify_totp(self._api_key, totp)
            data = _parse_response(resp)
            logger.info("verify_totp response: %s", data)

            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}

            token = (
                data.get("access_token")
                or (data.get("data") or {}).get("access_token", "")
            )
            if not token:
                return {
                    "success": False,
                    "error": "TOTP verified but no access token returned. "
                             "Please try again."
                }

            self._access_token = token
            self._logged_in    = True
            logger.info("TOTP verified OK, token: %s…", token[:12])
            return {"success": True, "data": data, "access_token": token}

        except Exception as e:
            logger.error("verify_totp failed: %s", e)
            return {"success": False, "error": str(e)}

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    # ── Portfolio ──────────────────────────────────────────────

    def get_holdings(self) -> dict:
        try:
            resp = self._mconnect.get_holdings()
            data = _parse_response(resp)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e), "data": {}}

    def get_order_book(self) -> dict:
        try:
            resp = self._mconnect.get_order_book()
            data = _parse_response(resp)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e), "data": {}}

    def get_positions(self) -> dict:
        try:
            resp = self._mconnect.get_net_position()
            data = _parse_response(resp)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e), "data": {}}

    def get_fund_summary(self) -> dict:
        try:
            resp = self._mconnect.get_fund_summary()
            data = _parse_response(resp)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e), "data": {}}

    # ── Orders ─────────────────────────────────────────────────

    def place_order(self, variety, symbol, exchange, transaction_type,
                    order_type, quantity, product, validity,
                    price="0", trigger_price="0",
                    disclosed_quantity="0", tag="") -> dict:
        """
        Full SDK signature (12 positional args):
          variety, symbol, exchange, transaction_type,
          order_type, quantity, product, validity,
          price, trigger_price, _disclosed_quantity, _tag
        """
        try:
            resp = self._mconnect.place_order(
                variety, symbol, exchange, transaction_type,
                order_type, quantity, product, validity,
                price, trigger_price,
                disclosed_quantity, tag,
            )
            data = _parse_response(resp)
            logger.info("Place order response: %s", data)

            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}

            return {"success": True, "data": data}
        except Exception as e:
            logger.error("Place order failed: %s", e)
            return {"success": False, "error": str(e)}

    def modify_order(self, order_id, order_type, quantity, price,
                     validity, trigger_price="0", disclosed_quantity="0") -> dict:
        try:
            resp = self._mconnect.modify_order(
                order_id, order_type, quantity, price,
                validity, trigger_price, disclosed_quantity,
            )
            data = _parse_response(resp)
            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def cancel_order(self, order_id: str) -> dict:
        try:
            resp = self._mconnect.cancel_order(order_id)
            data = _parse_response(resp)
            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Market data ────────────────────────────────────────────

    def get_ltp(self, instruments: list[str]) -> dict:
        try:
            resp = self._mconnect.get_ltp(instruments)
            data = _parse_response(resp)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e), "data": {}}

    def get_ohlc(self, instruments: list[str]) -> dict:
        try:
            resp = self._mconnect.get_ohlc(instruments)
            data = _parse_response(resp)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e), "data": {}}

    def logout(self):
        try:
            if self._mconnect:
                self._mconnect.logout()
        except Exception:
            pass
        self._logged_in    = False
        self._access_token = ""
        self._mconnect     = None
