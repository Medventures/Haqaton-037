"""smsc.kz client. Docs: https://smsc.kz/api/http/send/sms/"""

import logging
import os

import httpx

log = logging.getLogger("aqylroute.sms")

SMSC_URL = "https://smsc.kz/sys/send.php"


class SmsError(Exception):
    pass


def sms_enabled() -> bool:
    return bool(os.getenv("SMSC_LOGIN") and os.getenv("SMSC_PASSWORD"))


def send_sms(phone: str, message: str) -> None:
    """Send an SMS via smsc.kz. Without credentials, logs the message instead (local dev)."""
    if not sms_enabled():
        log.warning("SMSC_LOGIN not set, SMS not sent. To %s: %s", phone, message)
        return

    params = {
        "login": os.environ["SMSC_LOGIN"],
        "psw": os.environ["SMSC_PASSWORD"],
        "phones": phone,
        "mes": message,
        "fmt": 3,  # JSON response
        "charset": "utf-8",
    }
    if sender := os.getenv("SMSC_SENDER"):
        params["sender"] = sender

    try:
        resp = httpx.post(SMSC_URL, data=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        log.error("smsc.kz request failed: %s", e)
        raise SmsError("SMS service unavailable") from e

    if "error" in data:
        # Delivery reasons (e.g. operator rejected the sender) are only in the smsc.kz history.
        log.error(
            "smsc.kz error %s to %s****%s (sender=%s): %s",
            data.get("error_code"), phone[:4], phone[-3:], params.get("sender", "default"), data["error"],
        )
        raise SmsError(data["error"])
    log.info("SMS sent to %s, id=%s cnt=%s", phone, data.get("id"), data.get("cnt"))
