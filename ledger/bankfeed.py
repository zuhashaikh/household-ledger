"""Bank transactions from SimpleFIN Bridge (https://www.simplefin.org/protocol.html).

Setup:  a one-time setup token is base64 for a claim URL; POSTing to it returns the access URL
        (root URL with Basic-auth credentials). Keep that URL in the app's secrets.
Sync:   GET {root}/accounts?start-date&end-date (Unix seconds, at most 90 days apart). Amounts are
        positive for money in, negative for money out; pending transactions are left out by default.
"""
from __future__ import annotations

import base64
import datetime as dt
import re
from urllib.parse import unquote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("America/Chicago")
MAX_DAYS = 89  # the bridge allows 90 days per request; stay just inside it


class FeedError(Exception):
    pass


def claim(setup_token: str) -> str:
    """Exchange a one-time setup token for the access URL."""
    try:
        url = base64.b64decode(setup_token.strip() + "=" * (-len(setup_token.strip()) % 4)).decode().strip()
    except Exception as e:  # noqa: BLE001
        raise FeedError("That doesn't look like a SimpleFIN setup token. Copy the whole token again.") from e
    if not url.startswith("https://") and not url.startswith("http://localhost") and not url.startswith("http://127.0.0.1"):
        raise FeedError("That doesn't look like a SimpleFIN setup token. Copy the whole token again.")
    r = requests.post(url, timeout=30)
    if r.status_code == 403:
        raise FeedError("SimpleFIN says this token was already used or doesn't exist. Create a new setup token and try again.")
    r.raise_for_status()
    access = r.text.strip()
    if "@" not in access:
        raise FeedError("SimpleFIN returned something unexpected. Create a new setup token and try again.")
    return access


def _split(access_url: str) -> tuple[str, tuple[str, str]]:
    u = urlsplit(access_url)
    host = u.hostname + (f":{u.port}" if u.port else "")
    return urlunsplit((u.scheme, host, u.path.rstrip("/"), "", "")), (unquote(u.username or ""), unquote(u.password or ""))


def fetch(access_url: str, start: float, end: float) -> dict:
    base, auth = _split(access_url)
    r = requests.get(base + "/accounts", params={"start-date": int(start), "end-date": int(end), "version": 2},
                     auth=auth, timeout=90)
    if r.status_code == 402:
        raise FeedError("SimpleFIN needs payment before it will share data. Check your SimpleFIN subscription.")
    if r.status_code == 403:
        raise FeedError("SimpleFIN refused the connection. The access may have been revoked; connect the banks again.")
    r.raise_for_status()
    return r.json()


def messages(data: dict) -> list[str]:
    """Problems SimpleFIN reports (e.g. a bank that needs re-linking). Shown to the user as plain text."""
    out = [str(e.get("msg", "")) for e in data.get("errlist") or [] if isinstance(e, dict) and e.get("msg")]
    out += [str(e) for e in data.get("errors") or [] if e and str(e) not in out]
    return [re.sub(r"[<>]", "", m)[:300] for m in out]


def _last4(s: str) -> str:
    d = re.findall(r"\d{4}", s or "")
    return d[-1] if d else ""


def account_label(acct: dict, conns: dict, existing: list[str]) -> str:
    """Name an account so it lines up with accounts already in the ledger (matched on the last 4 digits)."""
    inst = (conns.get(acct.get("conn_id")) or {}).get("name") or (acct.get("org") or {}).get("name") or acct.get("conn_name") or ""
    name = str(acct.get("name") or "Account").strip()
    l4 = _last4(name) or _last4(str(acct.get("id", "")))
    if l4:
        hit = next((a for a in existing if re.sub(r"\D", "", a).endswith(l4)), None)
        if hit:
            return hit
    label = name if inst.lower() in name.lower() else f"{inst} {name}".strip()
    if l4 and l4 not in label:
        label += f" ••{l4}"
    return label


_PAYMENT = re.compile(r"payment thank you|automatic payment|autopay|payment to chase card|credit crd|crd epay|card payment|online payment|payment received|applecard gsbank|amex epayment|citi autopay|discover e-payment|capital one", re.I)
_TRANSFER = re.compile(r"zelle (payment )?from|transfer (from|to)|online transfer|moneyline|fid bkg|vanguard|schwab|robinhood|savings|xfer|venmo cashout|deposit", re.I)
_INCOME = re.compile(r"payroll|direct dep|dir dep|edi paymnt|salary|paycheck|irs treas|tax ref", re.I)


def guess_kind(desc: str, amt: float) -> str | None:
    """A first pass that keeps card payments, transfers and pay out of spending even when Claude isn't used."""
    if _PAYMENT.search(desc):
        return "Payment"
    if _INCOME.search(desc) and amt < 0:
        return "Income"
    if _TRANSFER.search(desc):
        return "Transfer"
    return None


def to_rows(data: dict, existing_accounts: list[str]) -> list[dict]:
    conns = {c.get("conn_id"): c for c in data.get("connections") or []}
    rows = []
    for a in data.get("accounts") or []:
        label = account_label(a, conns, existing_accounts)
        for t in a.get("transactions") or []:
            if t.get("pending"):
                continue
            ts = t.get("transacted_at") or t.get("posted")
            try:
                amt = -float(t.get("amount"))
                ts = int(ts)
            except (TypeError, ValueError):
                continue
            if not ts:
                continue
            desc = str(t.get("description") or (t.get("extra") or {}).get("payee") or "").strip()
            if not desc:
                continue
            rows.append({"date": dt.datetime.fromtimestamp(ts, TZ).date().isoformat(), "desc": desc, "amt": round(amt, 2),
                         "category": guess_kind(desc, -float(t.get("amount"))) or "Uncategorized", "account": label,
                         "ext_id": f"sfin:{a.get('id')}:{t.get('id')}"})
    return rows


def window(last_sync: float | None, now: float) -> tuple[float, float]:
    """From the last sync minus 5 days (as SimpleFIN recommends) — or 89 days back the first time — to now."""
    earliest = now - MAX_DAYS * 86400
    start = earliest if not last_sync else max(earliest, last_sync - 5 * 86400)
    return start, now
