"""Read a bank or card statement PDF with Claude and return clean transaction rows."""
from __future__ import annotations

import base64
import json
import re

from .logic import Ledger

PROMPT = """Extract every transaction from this bank or credit card statement for a household budget. Reply with ONLY one JSON object, no other text:
{{"account":"<short product name> ••<last 4 digits>","last4":"1234","periodStart":"YYYY-MM-DD","periodEnd":"YYYY-MM-DD","statementTotals":{{"purchases":number|null,"credits":number|null}},"transactions":[{{"date":"YYYY-MM-DD","description":"merchant text as printed","amount":12.34,"kind":"spend","category":"Grocery"}}]}}

Rules:
- Include each posted transaction in the account activity exactly once. Two identical lines on the same day are two transactions. Skip balance summaries, reward/points tables, interest-rate tables, minimum-payment tables and anything else that is not a transaction.
- amount: POSITIVE for money going out (purchases, debit-card purchases, checks, bill pays, fees, interest, ATM withdrawals). NEGATIVE for money coming back in (refunds, returns, statement credits, payments received by a card, deposits, transfers in).
- kind is one of: spend, refund, payment, transfer, income, fee, interest. A payment to a credit card (from either side) is "payment": it is not spending, because the card's own statement holds the purchases. Moves between the household's own accounts, and money received from another person or another bank (Zelle, online transfers, deposits from another bank), are "transfer"; keep the sending bank or person's name in the description exactly as printed. Paychecks are "income".
- Use the statement's year for every date; if the period spans December–January, give each date its correct year.
- statementTotals: the statement's own printed total for purchases (or debits) and for payments+credits (or deposits+credits), as positive numbers, if printed; otherwise null.
- category: "Payment" for kind payment, "Transfer" for transfer, "Income" for income. Otherwise exactly one of these budget lines: {lines}. If none fits, "Other".
- How this household maps common spending categories onto its budget lines: {catmap}.
- Merchants this household has already categorized (follow these):
{known}
- Known accounts (if this statement is one of them by last 4 digits, use that exact account name): {accounts}
"""


def build_prompt(ledger: Ledger) -> str:
    seen: dict[str, str] = {}
    for t in ledger.txns:
        c = ledger.cat_of(t)
        if not ledger.is_excluded(c) and t.get("mk") and t["mk"] not in seen:
            seen[t["mk"]] = c
    seen.update(ledger.rules.get("recat") or {})
    seen.update({k: v["line"] for k, v in (ledger.rules.get("learn") or {}).items() if v.get("line")})
    known = "\n".join(f"{k} → {v}" for k, v in list(seen.items())[:120]) or "(none yet)"
    catmap = "; ".join(f"{k} → {v}" for k, v in (ledger.rules.get("catmap") or {}).items())
    accts = ledger.accounts()
    return PROMPT.format(lines=json.dumps(ledger.budget_lines()), catmap=catmap or "(none)", known=known,
                         accounts=json.dumps(accts) if accts else "(none yet)")


def _parse_date(s) -> str | None:
    s = str(s or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        y = m[3] if len(m[3]) == 4 else "20" + m[3]
        return f"{y}-{int(m[1]):02d}-{int(m[2]):02d}"
    return None


def _amount(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    if not s:
        return None
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")")) or "-$" in s
    num = re.sub(r"[^0-9.]", "", s)
    try:
        n = float(num)
    except ValueError:
        return None
    return -n if neg else n


def read_statement(pdf: bytes, ledger: Ledger, api_key: str, model: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=300)
    content = [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                         "data": base64.standard_b64encode(pdf).decode()}},
        {"type": "text", "text": build_prompt(ledger)},
    ]
    with client.messages.stream(model=model, max_tokens=32000, messages=[{"role": "user", "content": content}]) as stream:
        msg = stream.get_final_message()
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Claude's answer had no JSON in it.")
    return normalize(json.loads(m.group(0)), ledger)


def normalize(res: dict, ledger: Ledger) -> dict:
    if not isinstance(res, dict) or not isinstance(res.get("transactions"), list):
        raise ValueError("Couldn't find transactions in that statement.")
    acct = str(res.get("account") or "").strip() or "Unnamed account"
    last4 = str(res.get("last4") or "") or (re.search(r"(\d{4})\s*$", acct).group(1) if re.search(r"(\d{4})\s*$", acct) else "")
    if last4:
        hit = next((a for a in ledger.accounts() if re.sub(r"\D", "", a).endswith(last4)), None)
        if hit:
            acct = hit
    lines = set(ledger.budget_lines())
    rows = []
    for t in res["transactions"]:
        date, amt = _parse_date(t.get("date")), _amount(t.get("amount"))
        desc = str(t.get("description") or "").strip()
        if not date or amt is None or not desc:
            continue
        kind = t.get("kind") or ""
        cat = str(t.get("category") or "").strip() or "Uncategorized"
        if kind == "payment":
            cat = "Payment"
        elif kind == "transfer":
            cat = "Transfer"
        elif kind == "income":
            cat = "Income"
        elif cat not in lines and cat != "Uncategorized":
            cat = ledger.rules["catmap"].get(cat, cat)
        rows.append({"date": date, "desc": desc, "amt": amt, "category": cat, "account": acct, "kind": kind})
    if not rows:
        raise ValueError("Couldn't find any transactions in that statement.")
    totals = res.get("statementTotals") or {}
    return {"account": acct, "rows": rows, "totals": totals,
            "start": _parse_date(res.get("periodStart")), "end": _parse_date(res.get("periodEnd"))}


CATEGORIZE = """Categorize these bank transactions for a household budget. Reply with ONLY a JSON array, one object per transaction, in the same order:
[{{"i":0,"kind":"spend","category":"Grocery"}}]

- kind is one of: spend, refund, payment, transfer, income, fee, interest. A payment to a credit card is "payment". Money sent between the household's own accounts, or received from another person or bank (Zelle, transfers, deposits), is "transfer". Paychecks are "income".
- category: "Payment", "Transfer" or "Income" for those kinds. Otherwise exactly one of these budget lines: {lines}. If none fits, "Other".
- How this household maps common spending categories onto its budget lines: {catmap}.
- Merchants this household has already categorized (follow these):
{known}

Transactions (amount: positive = money out, negative = money in):
{rows}
"""


def categorize(rows: list[dict], ledger: Ledger, api_key: str, model: str) -> list[dict]:
    """Fill in category for rows the household's own rules don't cover. One Claude call for the whole batch."""
    import anthropic

    if not rows:
        return rows
    p = build_prompt(ledger)
    known = p.split("(follow these):\n", 1)[1].split("\n- Known accounts", 1)[0] if "(follow these):\n" in p else "(none yet)"
    catmap = "; ".join(f"{k} → {v}" for k, v in (ledger.rules.get("catmap") or {}).items()) or "(none)"
    listing = "\n".join(f"{i}. {r['desc']} | {r['amt']:.2f} | {r['account']}" for i, r in enumerate(rows))
    client = anthropic.Anthropic(api_key=api_key, timeout=120, max_retries=1)
    msg = client.messages.create(model=model, max_tokens=8000, messages=[{"role": "user", "content": CATEGORIZE.format(
        lines=json.dumps(ledger.budget_lines()), catmap=catmap, known=known, rows=listing)}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return rows
    lines = set(ledger.budget_lines())
    for x in json.loads(m.group(0)):
        try:
            r = rows[int(x.get("i"))]
        except (TypeError, ValueError, IndexError):
            continue
        kind = x.get("kind") or ""
        cat = {"payment": "Payment", "transfer": "Transfer", "income": "Income"}.get(kind) or str(x.get("category") or "Other")
        if cat not in lines and cat not in ("Payment", "Transfer", "Income", "Other"):
            cat = ledger.rules["catmap"].get(cat, cat)
        r["category"] = cat
    return rows
