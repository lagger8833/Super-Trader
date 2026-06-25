"""
core/api_client.py
Validated against: tradingapi.mstock.com/docs/v1/typeA/User/

AUTH FLOW (two paths):
  Path A — OTP:   login(user, pwd) → generate_session(api_key, otp, "L") → access_token
  Path B — TOTP:  login(user, pwd) → verify_totp(api_key, totp)          → access_token

TOKEN LOCATION IN RESPONSES (from docs):
  generate_session / verify_totp success shape:
    {"status": "success", "data": {"access_token": "eyJ...", "api_key": "...", ...}}
  access_token is ALWAYS inside data["data"], never at the root.

AUTHORIZATION HEADER for all post-auth calls (from docs):
  Authorization: token <api_key>:<access_token>
  X-Mirae-Version: 1

The SDK (MConnect) should set this header internally after a successful
generate_session/verify_totp. As a guaranteed fallback we also make direct
requests.Session calls with the correct header set explicitly.

FUND SUMMARY RESPONSE (from docs):
  {"status": "success", "data": [{"AVAILABLE_BALANCE": "...", "SUM_OF_ALL": "...", ...}]}
  data is a list of segment dicts with ALL-UPPERCASE field names.
"""

import logging
import requests as _requests
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.mstock.trade/openapi/typea"


def _parse_response(resp) -> dict:
    """Extract JSON dict from SDK response or raw requests.Response."""
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
    Return error message if body has status=error, else None.
    The API returns HTTP 200 for many errors with status:"error" in body.
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
        self._mconnect     = None
        self._logged_in    = False
        self._api_key      = ""
        self._checksum     = "L"
        self._access_token = ""
        self._user_id      = ""
        # Dedicated requests.Session for direct REST calls with auth header
        self._session      = _requests.Session()

    @classmethod
    def get(cls) -> "APIClient":
        if cls._instance is None:
            cls._instance = APIClient()
        return cls._instance

    def _init_mconnect(self):
        from tradingapi_a.mconnect import MConnect
        self._mconnect = MConnect()

    def _auth_headers(self) -> dict:
        """
        Build the Authorization header exactly as documented:
          Authorization: token api_key:access_token
          X-Mirae-Version: 1
        """
        return {
            "Authorization": f"token {self._api_key}:{self._access_token}",
            "X-Mirae-Version": "1",
        }

    def _inject_auth_into_sdk(self, token: str):
        """
        After a successful auth, attempt to push the correct Authorization header
        into the MConnect SDK's internal requests.Session so its built-in methods
        (get_holdings, place_order, etc.) also carry the correct header.

        The SDK should do this itself, but Issue #26 shows it sometimes uses
        'token access_token' instead of 'token api_key:access_token'.
        We try every known attribute name the SDK might use for its session.
        """
        auth_value = f"token {self._api_key}:{token}"
        headers = {"Authorization": auth_value, "X-Mirae-Version": "1"}

        # Also update our own direct session
        self._session.headers.update(headers)

        if self._mconnect is None:
            return

        # Try known setter methods first
        for method in ("set_access_token", "setAccessToken"):
            if callable(getattr(self._mconnect, method, None)):
                try:
                    getattr(self._mconnect, method)(token)
                    logger.debug("Token injected via %s()", method)
                except Exception as e:
                    logger.debug("Method %s() failed: %s", method, e)

        # Patch the internal requests.Session directly
        for attr in ("_session", "session", "_http_session", "http", "s", "req_session"):
            sess = getattr(self._mconnect, attr, None)
            if sess is not None and hasattr(sess, "headers"):
                try:
                    sess.headers.update(headers)
                    logger.debug("Auth header patched into mconnect.%s.headers", attr)
                except Exception as e:
                    logger.debug("Patch via %s failed: %s", attr, e)

        # Also try setting token attributes the SDK might read
        for attr in ("access_token", "_access_token", "token", "_token"):
            if hasattr(self._mconnect, attr):
                try:
                    setattr(self._mconnect, attr, token)
                    logger.debug("Token attribute %s set on mconnect", attr)
                except Exception:
                    pass

    # ── Auth Step 1: Login ────────────────────────────────────

    def login(self, user_id: str, password: str) -> dict:
        """
        Doc: POST /openapi/typea/connect/login
        Body: username, password
        Success: {"status":"success","data":{"ugid":"...","cid":"...","nm":"...",...}}
        On success mStock sends SMS OTP (if TOTP not enabled on account).
        """
        self._init_mconnect()
        self._user_id = user_id
        try:
            resp = self._mconnect.login(user_id, password)
            data = _parse_response(resp)
            logger.info("login() response status=%s", data.get("status"))

            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}

            return {"success": True, "data": data}
        except Exception as e:
            logger.error("login() exception: %s", e)
            return {"success": False, "error": str(e)}

    # ── Auth Step 2 Path A: OTP → access_token ───────────────

    def generate_session(self, otp: str) -> dict:
        """
        Doc: POST /openapi/typea/session/token
        Body: api_key, request_token=OTP, checksum="L"
        Success response shape (from docs):
          {"status":"success","data":{"access_token":"eyJ...","api_key":"...","user_id":"...",...}}
        access_token is inside data["data"], NOT at root.
        """
        try:
            resp = self._mconnect.generate_session(
                self._api_key, otp, self._checksum
            )
            data = _parse_response(resp)
            logger.info("generate_session() response status=%s", data.get("status"))

            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}

            # access_token is inside data["data"] per the docs
            inner = data.get("data") or {}
            token = inner.get("access_token", "")

            if not token:
                logger.error("generate_session() succeeded but no access_token in data['data']. Full response: %s", data)
                return {
                    "success": False,
                    "error": "Session created but no access token received. "
                             "Please try again.",
                }

            self._access_token = token
            self._logged_in    = True
            self._inject_auth_into_sdk(token)
            logger.info("generate_session() OK, token prefix: %s…", token[:16])
            return {"success": True, "data": data, "access_token": token}

        except Exception as e:
            logger.error("generate_session() exception: %s", e)
            return {"success": False, "error": str(e)}

    # ── Auth Step 2 Path B: TOTP → access_token ──────────────

    def verify_totp(self, totp: str) -> dict:
        """
        Doc: POST /openapi/typea/session/verifytotp
        Body: api_key, totp
        Success response: same shape as generate_session.
        access_token is inside data["data"].
        """
        try:
            resp = self._mconnect.verify_totp(self._api_key, totp)
            data = _parse_response(resp)
            logger.info("verify_totp() response status=%s", data.get("status"))

            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}

            inner = data.get("data") or {}
            token = inner.get("access_token", "")

            if not token:
                logger.error("verify_totp() succeeded but no access_token. Full response: %s", data)
                return {
                    "success": False,
                    "error": "TOTP accepted but no access token received. "
                             "Please try again.",
                }

            self._access_token = token
            self._logged_in    = True
            self._inject_auth_into_sdk(token)
            logger.info("verify_totp() OK, token prefix: %s…", token[:16])
            return {"success": True, "data": data, "access_token": token}

        except Exception as e:
            logger.error("verify_totp() exception: %s", e)
            return {"success": False, "error": str(e)}

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    # ── Fund Summary (direct REST, guaranteed auth header) ────

    def get_fund_summary(self) -> dict:
        """
        Doc: GET /openapi/typea/user/fundsummary
        Headers: Authorization: token api_key:access_token
        Response: {"status":"success","data":[{"AVAILABLE_BALANCE":"...","SUM_OF_ALL":"...",...}]}
        data is a LIST of segment dicts with UPPERCASE keys.

        We call this directly via requests (not SDK) to guarantee the
        Authorization header is exactly 'token api_key:access_token'.
        """
        try:
            # First try SDK method (in case it has the header right)
            resp = self._mconnect.get_fund_summary()
            data = _parse_response(resp)

            # If SDK returned an auth error, retry with direct REST call
            err = _check_body_error(data)
            if err and ("token" in err.lower() or "auth" in err.lower()
                        or "api" in err.lower() or "suspend" in err.lower()):
                logger.warning("SDK fund_summary auth error, retrying with direct REST: %s", err)
                data = self._direct_get("user/fundsummary")

            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err, "data": {}}

            return {"success": True, "data": data}
        except Exception as e:
            logger.warning("SDK get_fund_summary() failed (%s), trying direct REST", e)
            try:
                data = self._direct_get("user/fundsummary")
                err = _check_body_error(data)
                if err:
                    return {"success": False, "error": err, "data": {}}
                return {"success": True, "data": data}
            except Exception as e2:
                return {"success": False, "error": str(e2), "data": {}}

    def _direct_get(self, path: str) -> dict:
        """Make a direct GET request with the correct Authorization header."""
        url = f"{BASE_URL}/{path}"
        r = self._session.get(url, headers=self._auth_headers(), timeout=15)
        r.raise_for_status()
        return r.json()

    def _direct_post(self, path: str, data: dict) -> dict:
        """Make a direct POST (form-encoded) with correct Authorization header."""
        url = f"{BASE_URL}/{path}"
        r = self._session.post(
            url, data=data, headers=self._auth_headers(), timeout=15
        )
        r.raise_for_status()
        return r.json()

    # ── Portfolio ─────────────────────────────────────────────

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

    # ── Orders ────────────────────────────────────────────────

    def place_order(self, variety, symbol, exchange, transaction_type,
                    order_type, quantity, product, validity,
                    price="0", trigger_price="0",
                    disclosed_quantity="0", tag="") -> dict:
        """
        Doc: POST /openapi/typea/orders/{variety}
        12 positional args required by SDK: last two are _disclosed_quantity, _tag.
        """
        try:
            resp = self._mconnect.place_order(
                variety, symbol, exchange, transaction_type,
                order_type, quantity, product, validity,
                price, trigger_price,
                disclosed_quantity, tag,
            )
            data = _parse_response(resp)
            logger.info("place_order() response: %s", data)
            err = _check_body_error(data)
            if err:
                return {"success": False, "error": err}
            return {"success": True, "data": data}
        except Exception as e:
            logger.error("place_order() exception: %s", e)
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

    # ── Market Data ───────────────────────────────────────────

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

    # ── Logout ────────────────────────────────────────────────

    def logout(self):
        """Doc: GET /openapi/typea/logout  Headers: Authorization: token api_key:access_token"""
        try:
            if self._mconnect:
                self._mconnect.logout()
        except Exception:
            pass
        self._logged_in    = False
        self._access_token = ""
        self._mconnect     = None
        self._session      = _requests.Session()
