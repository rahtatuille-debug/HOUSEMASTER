"""
Safaricom's M-Pesa API (Daraja): sign-in, the PIN prompt on the payer's
phone (STK Push), checking a prompt's result, and registering the URLs
where paybill payments are confirmed (C2B). Every call has a timeout and
raises DarajaError with a readable message; nothing here touches the
database.
"""
import base64
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

HOSTS = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}
TIMEOUT = 20
NAIROBI = ZoneInfo("Africa/Nairobi")


class DarajaError(Exception):
    pass


class Credentials:
    """What a call needs: the shortcode, how it's paid (paybill or till), and the keys."""

    def __init__(self, *, environment, shortcode, consumer_key, consumer_secret, passkey, kind="paybill", till_number=""):
        self.environment = environment if environment in HOSTS else "sandbox"
        self.shortcode = str(shortcode).strip()
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.passkey = passkey
        self.kind = kind
        self.till_number = str(till_number or "").strip()

    @property
    def host(self):
        return HOSTS[self.environment]


def _post(creds, path, body, token):
    try:
        response = requests.post(f"{creds.host}{path}", json=body, timeout=TIMEOUT,
                                 headers={"Authorization": f"Bearer {token}"})
    except requests.RequestException:
        raise DarajaError("M-Pesa couldn't be reached. Please try again in a moment.")
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        raise DarajaError(data.get("errorMessage") or data.get("ResponseDescription")
                          or f"M-Pesa answered {response.status_code}.")
    return data


def access_token(creds):
    if not (creds.consumer_key and creds.consumer_secret):
        raise DarajaError("The M-Pesa consumer key and secret aren't set.")
    try:
        response = requests.get(f"{creds.host}/oauth/v1/generate", params={"grant_type": "client_credentials"},
                                auth=(creds.consumer_key, creds.consumer_secret), timeout=TIMEOUT)
    except requests.RequestException:
        raise DarajaError("M-Pesa couldn't be reached. Please try again in a moment.")
    if response.status_code != 200:
        raise DarajaError("M-Pesa didn't accept the consumer key and secret.")
    try:
        return response.json()["access_token"]
    except (ValueError, KeyError):
        raise DarajaError("M-Pesa sent an unexpected answer when signing in.")


def _password(creds, timestamp):
    return base64.b64encode(f"{creds.shortcode}{creds.passkey}{timestamp}".encode()).decode()


def _timestamp():
    return datetime.now(NAIROBI).strftime("%Y%m%d%H%M%S")


def stk_push(creds, *, phone, amount, account_reference, description, callback_url):
    """Ask M-Pesa to show the payer a PIN prompt. Returns (merchant_request_id, checkout_request_id)."""
    token = access_token(creds)
    timestamp = _timestamp()
    till = creds.kind == "till"
    data = _post(creds, "/mpesa/stkpush/v1/processrequest", {
        "BusinessShortCode": creds.shortcode, "Password": _password(creds, timestamp), "Timestamp": timestamp,
        "TransactionType": "CustomerBuyGoodsOnline" if till else "CustomerPayBillOnline",
        "Amount": int(amount), "PartyA": phone, "PartyB": creds.till_number if till else creds.shortcode,
        "PhoneNumber": phone, "CallBackURL": callback_url,
        "AccountReference": account_reference[:12], "TransactionDesc": description[:13],
    }, token)
    if str(data.get("ResponseCode")) != "0" or not data.get("CheckoutRequestID"):
        raise DarajaError(data.get("CustomerMessage") or data.get("ResponseDescription") or "M-Pesa didn't send the prompt.")
    return data.get("MerchantRequestID", ""), data["CheckoutRequestID"]


def stk_query(creds, checkout_request_id):
    """The result of a prompt: (result_code or None while it's still waiting, description)."""
    token = access_token(creds)
    timestamp = _timestamp()
    try:
        data = _post(creds, "/mpesa/stkpushquery/v1/query", {
            "BusinessShortCode": creds.shortcode, "Password": _password(creds, timestamp), "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }, token)
    except DarajaError as err:
        # Asked too soon, M-Pesa answers with an error saying it's still being processed.
        if _still_waiting(str(err)):
            return None, str(err)
        raise
    code = data.get("ResultCode")
    description = data.get("ResultDesc", "")
    # 4999 ("The transaction is still under processing") also means the payer hasn't answered yet.
    if code in (None, "") or str(code) in STILL_WAITING_CODES or _still_waiting(description):
        return None, description
    return int(code), description


STILL_WAITING_CODES = {"4999", "500.001.1001"}


def _still_waiting(text):
    text = (text or "").lower()
    return "under processing" in text or "being processed" in text


def register_c2b(creds, *, confirmation_url, validation_url):
    """Tell M-Pesa where to send payments made straight to the paybill or till."""
    token = access_token(creds)
    _post(creds, "/mpesa/c2b/v1/registerurl", {
        "ShortCode": creds.shortcode, "ResponseType": "Completed",
        "ConfirmationURL": confirmation_url, "ValidationURL": validation_url,
    }, token)
