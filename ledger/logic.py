"""Ledger rules and math. Pure functions over plain dicts, ported from the Zuha & Aneeq Ledger page.

Transaction dict fields (snake_case):
  id, month, date (YYYY-MM-DD), desc, spend (+ money out, - money in), category (as imported),
  account, mk (merchant key), cat_override, person, project, proj_item, for_line, moved_from,
  statement_id, added_by
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PEOPLE = {"zuha": "Zuha", "aneeq": "Aneeq", "shared": "Shared"}
PAYER_LABEL = {"zuha": "Zuha (Chase + pay)", "aneeq": "Aneeq (Wells Fargo)", "shared": "Joint", "unset": "Payer not set"}
SECTIONS = [("Home Budget", "Core budget"), ("Extras I", "Extras I"), ("Extras II (Split 50:50)", "Extras II")]
DEFAULT_SECTION = "Extras II (Split 50:50)"
DEFAULT_EXCLUDE = re.compile(r"transfer|credit card payment|payment|paycheck|income|deposit|refund reversal", re.I)


def empty_rules() -> dict:
    return {"merchant": {}, "account": {}, "category": {}, "recat": {}, "exclude": {}, "catmap": {},
            "payer": {}, "contrib": [], "accounts": [], "patcat": []}


def norm_rules(r: dict | None) -> dict:
    out = empty_rules()
    out.update(r or {})
    return out


def merchant_key(desc: str) -> str:
    d = str(desc or "").lower()
    k = d.split("*")[0]
    k = re.sub(r"#\s*\d+", "", k)
    k = re.sub(r"\d{3,}", "", k)
    k = re.sub(r"[^a-z&' ]+", " ", k)
    k = re.sub(r"\s+", " ", k).strip()
    k = " ".join(k.split(" ")[:3])
    return k or d.strip()


_PREFIXES = re.compile(r"^(card purchase with pin|card purchase|debit card purchase|purchase authorized on|pos purchase|pos|recurring payment|ach debit|online transfer to|online payment to|web pymt|sq|tst|sp|py|dd)\b\s*")


def learn_key(desc: str) -> str:
    """Merchant identity for remembered choices: the merchant's name without store numbers, card prefixes
    or reference codes. Keeps the person in Zelle descriptions, so each payee is remembered separately."""
    d = str(desc or "").lower()
    if "*" in d:
        head, tail = d.split("*", 1)
        # Payment processors put the real merchant after the "*" (PAYPAL *EBAY, SQ *CAFE, TST* GRILL).
        processor = head.strip() in {"paypal", "pp", "sq", "tst", "sp", "py", "dd", "ppl", "gglpay", "google", "apl", "venmo"}
        d = tail if processor or len(head.strip()) < 4 else head
    d = re.sub(r"[^a-z0-9&' ]+", " ", d)
    d = _PREFIXES.sub("", d.strip())
    words = [w for w in d.split() if not re.search(r"\d", w) and len(w) > 1 and w not in {"tx", "ca", "wa", "ny", "nj", "nc", "com", "bill"}]
    return " ".join(words[:5]) or d.strip()


def fnv_id(s: str) -> str:
    """Same id scheme as the original page (FNV-1a 32-bit, base 36), so re-imports dedupe against seeded data."""
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if h == 0:
        return "0"
    out = ""
    while h:
        h, r = divmod(h, 36)
        out = digits[r] + out
    return out


def month_label(m: str) -> str:
    import calendar
    y, mo = m.split("-")
    return f"{calendar.month_name[int(mo)]} {y}"


@dataclass
class Ledger:
    rules: dict = field(default_factory=empty_rules)
    plan: dict = field(default_factory=lambda: {"budgets": {}, "byMonth": {}, "groups": {}})
    projects: list = field(default_factory=list)
    txns: list = field(default_factory=list)

    def __post_init__(self):
        self.rules = norm_rules(self.rules)
        self.plan.setdefault("budgets", {})
        self.plan.setdefault("byMonth", {})
        self.plan.setdefault("groups", {})

    # ---------- lookups ----------
    def shift_rules(self) -> list[dict]:
        """Merchants that bill at the end of a month for the next one (e.g. Ota Swim): charges on or after
        `from_day` count toward the following month."""
        r = self.rules.get("shift")
        if r is None:
            r = [{"match": "ota scuba swim", "from_day": 20, "label": "Ota Swim"}]
        return [x for x in r if x and x.get("match")]

    @staticmethod
    def _merchant_root(desc: str) -> str:
        words = [w for w in learn_key(desc).split() if w not in {"www", "the", "card", "purchase"}]
        return words[0] if words else ""

    def refund_matches(self) -> dict[str, dict]:
        """Refunds paired with the earlier charge they reverse: same account, same amount to the cent, same
        merchant, charged within 60 days before. A refund counts in its charge's month so the two net to zero."""
        sig = (len(self.txns), sum(1 for t in self.txns if t.get("spend", 0) < 0))
        if getattr(self, "_refund_sig", None) == sig:
            return self._refund_map
        import datetime as _dt
        day = lambda d: _dt.date.fromisoformat(d).toordinal()
        charges: dict[tuple, list] = {}
        for t in self.txns:
            if t.get("spend", 0) > 0 and not t.get("synthetic"):
                charges.setdefault((t.get("account"), round(t["spend"], 2), self._merchant_root(t.get("desc", ""))), []).append(t)
        used, out = set(), {}
        refunds = sorted((t for t in self.txns if t.get("spend", 0) < 0 and not t.get("synthetic")), key=lambda t: t["date"])
        for r in refunds:
            if "zelle" in str(r.get("desc", "")).lower() or self.contrib_of(r):
                continue
            root = self._merchant_root(r.get("desc", ""))
            if not root:
                continue
            cands = [c for c in charges.get((r.get("account"), round(-r["spend"], 2), root), [])
                     if c["id"] not in used and 0 <= day(r["date"]) - day(c["date"]) <= 60]
            if cands:
                c = max(cands, key=lambda c: c["date"])  # the most recent matching charge
                used.add(c["id"])
                out[r["id"]] = c
        self._refund_sig, self._refund_map = sig, out
        return out

    def month_of(self, t: dict) -> str:
        """The month a charge counts in: its own month, unless it was moved by hand, it's a refund of an earlier
        charge (then it counts with that charge), or a next-month rule applies."""
        if t.get("moved_from") or t.get("synthetic"):
            return t["month"]
        if t.get("spend", 0) < 0:
            c = self.refund_matches().get(t.get("id"))
            if c:
                return self.month_of(c)
        d = str(t.get("date") or "")
        base = d[:7] or t.get("month", "")
        key = learn_key(t.get("desc", ""))
        for x in self.shift_rules():
            if str(x["match"]).lower() in key and len(d) >= 10 and int(d[8:10]) >= int(x.get("from_day") or 20):
                y, mo = int(base[:4]), int(base[5:7]) + 1
                return f"{y + (mo > 12)}-{(mo - 1) % 12 + 1:02d}"
        return base

    def shifted(self, t: dict) -> bool:
        return not t.get("moved_from") and not t.get("synthetic") and self.month_of(t) != str(t.get("date", ""))[:7]

    def months(self) -> list[str]:
        return sorted({self.month_of(t) for t in self.txns})

    def deductions(self) -> list[dict]:
        """Budget lines paid straight out of someone's paycheck, so they never appear on a statement.
        Each counts as spent every month: the given amount, or that month's budget for the line."""
        d = self.rules.get("deductions")
        if d is None:  # not set yet: Zuha's health insurance comes out of her Remote pay
            d = [{"line": "Health Insurance", "who": "zuha"}]
        return [x for x in d if x and x.get("line")]

    def deduction_txns(self, m: str) -> list[dict]:
        out = []
        for x in self.deductions():
            amt = float(x.get("amount") or 0) or float(self.plan_for(m).get(x["line"]) or 0)
            if amt:
                who = x.get("who") or "zuha"
                out.append({"id": f"ded:{m}:{x['line']}", "month": m, "date": f"{m}-01", "synthetic": True,
                            "desc": f"{x['line']} (taken from {PEOPLE.get(who, who)}'s pay)", "spend": amt,
                            "category": x["line"], "cat_override": x["line"], "account": "Paycheck deduction",
                            "payer": who, "person": who if x.get("counts_toward") == "self" else None, "mk": ""})
        return out

    def month_txns(self, m: str, with_deductions: bool = True) -> list[dict]:
        own = [t for t in self.txns if self.month_of(t) == m]
        return own + (self.deduction_txns(m) if with_deductions and own else [])

    def plan_for(self, m: str) -> dict:
        return self.plan["byMonth"].get(m) or self.plan["budgets"]

    def budget_lines(self) -> list[str]:
        s = set(self.plan["budgets"])
        for v in self.plan["byMonth"].values():
            s |= set(v)
        return sorted(s, key=str.lower)

    def all_categories(self, m: str | None = None) -> list[str]:
        s = set(self.plan["budgets"]) | (set(self.plan_for(m)) if m else set())
        for t in self.txns:
            s.add(self.cat_of(t))
        return sorted(s, key=str.lower)

    def accounts(self) -> list[str]:
        return sorted({t["account"] for t in self.txns if t.get("account")})

    def section_of(self, cat: str) -> str:
        g = self.plan["groups"].get(cat)
        return g if any(k == g for k, _ in SECTIONS) else "other"

    # ---------- classification ----------
    def pat_cat(self, t: dict) -> str | None:
        d = str(t.get("desc") or "").lower().replace("-", "")
        for r in self.rules.get("patcat") or []:
            if not r or not r.get("match") or not r.get("cat"):
                continue
            try:
                if re.search(r"\b" + r["match"] + r"\b", d) and not (r.get("not") and re.search(r["not"], d)):
                    return r["cat"]
            except re.error:
                continue
        return None

    def learned(self, t: dict) -> dict:
        return (self.rules.get("learn") or {}).get(learn_key(t.get("desc", ""))) or {}

    def cat_of(self, t: dict) -> str:
        return (t.get("cat_override") or self.learned(t).get("line") or self.pat_cat(t) or self.rules["recat"].get(t.get("mk", ""))
                or self.rules["catmap"].get(t.get("category", "")) or t.get("category") or "Uncategorized")

    def is_excluded(self, cat: str) -> bool:
        v = self.rules["exclude"].get(cat)
        if v is True or v is False:
            return v
        return bool(DEFAULT_EXCLUDE.search(cat or ""))

    def resolve(self, t: dict) -> tuple[str | None, str]:
        if t.get("person"):
            return t["person"], "this transaction only"
        if self.learned(t).get("who"):
            return self.learned(t)["who"], "remembered for this merchant"
        mk = t.get("mk", "")
        if self.rules["merchant"].get(mk):
            return self.rules["merchant"][mk], "merchant rule"
        if t.get("account") and self.rules["account"].get(t["account"]):
            return self.rules["account"][t["account"]], "account rule"
        c = self.cat_of(t)
        if self.rules["category"].get(c):
            return self.rules["category"][c], "line owner"
        return None, "not assigned yet"

    def payer_of(self, t: dict) -> str | None:
        return t.get("payer") or self.rules["payer"].get(t.get("account") or "") or None

    def contrib_of(self, t: dict) -> dict | None:
        if not t.get("spend"):
            return None
        d = str(t.get("desc") or "").lower()
        for r in self.rules.get("contrib") or []:
            if r and r.get("match") and str(r["match"]).lower() in d:
                return r
        return None

    # ---------- big expenses ----------
    def proj_by_id(self, pid: str | None) -> dict | None:
        return next((p for p in self.projects if p.get("id") == pid), None) if pid else None

    def proj_rules(self) -> list[dict]:
        """Charges that always count toward a big expense, matched on the description (a regular expression).
        Default: PayPal pay-later repayments from Chase and Wayfair go to Furniture."""
        r = self.rules.get("projrule")
        if r is None:
            r = [{"match": r"pypl\s*paymthly|paypal\s*pay\s*monthly|pay\s*in\s*4|payin4|wayfair", "project": "furniture",
                  "label": "PayPal pay-later & Wayfair"}]
        return [x for x in r if x and x.get("match") and self.proj_by_id(x.get("project"))]

    def proj_of(self, t: dict) -> dict | None:
        if t.get("synthetic"):
            return None
        if t.get("project"):
            return self.proj_by_id(t["project"])  # "none" means taken off a big expense on purpose
        pid = self.learned(t).get("project")
        if pid and self.proj_by_id(pid):
            return self.proj_by_id(pid)
        d = str(t.get("desc") or "").lower()
        for x in self.proj_rules():
            try:
                if re.search(x["match"], d):
                    return self.proj_by_id(x["project"])
            except re.error:
                continue
        return None

    @staticmethod
    def fund_amt(f: dict) -> float:
        if f.get("months"):
            return sum(float(v or 0) for v in f["months"].values())
        return float(f.get("amount") or 0)

    def fund_owner(self, f: dict) -> str:
        if f.get("line"):
            return self.rules["category"].get(f["line"]) or "shared"
        return f.get("owner") or "shared"

    def proj_stats(self, p: dict) -> dict:
        est = sum(float(i.get("est") or 0) for i in p.get("items") or [])
        fz = fa = 0.0
        for f in p.get("funding") or []:
            a, o = self.fund_amt(f), self.fund_owner(f)
            if o == "zuha":
                fz += a
            elif o == "aneeq":
                fa += a
            else:
                fz += a / 2
                fa += a / 2
        funded = fz + fa
        short = est - funded
        base = funded + max(0.0, short)
        plan_pct = (fz + max(0.0, short) / 2) / base if base else 0.5
        z_pct = {"even": 0.5, "zuha": 1.0, "aneeq": 0.0}.get(p.get("split") or "", plan_pct)
        txns = sorted([t for t in self.txns if (self.proj_of(t) or {}).get("id") == p["id"] and not self.contrib_of(t)], key=lambda t: t["date"])
        spent = sum(t["spend"] for t in txns)
        names = {i["name"] for i in p.get("items") or []}
        by_item: dict[str, float] = {}
        unmatched = 0.0
        for t in txns:
            if t.get("proj_item") in names:
                by_item[t["proj_item"]] = by_item.get(t["proj_item"], 0) + t["spend"]
            else:
                unmatched += t["spend"]
        return {"est": est, "funded": funded, "fz": fz, "fa": fa, "short": short, "plan_pct": plan_pct,
                "z_pct": z_pct, "spent": spent, "txns": txns, "by_item": by_item, "unmatched": unmatched}

    def tx_z_share(self, t: dict, pj: dict) -> float:
        it = next((i for i in pj.get("items") or [] if i.get("name") == t.get("proj_item")), None) if t.get("proj_item") else None
        if it and it.get("who"):
            return {"zuha": 1.0, "aneeq": 0.0}.get(it["who"], 0.5)
        return self.proj_stats(pj)["z_pct"]

    def asides_for(self, m: str) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for p in self.projects:
            for f in p.get("funding") or []:
                if f.get("line") and f.get("months") and float(f["months"].get(m) or 0):
                    out.setdefault(f["line"], []).append({"name": p["name"], "amt": float(f["months"][m])})
        return out

    # ---------- month math ----------
    def compute(self, m: str) -> dict:
        cats: dict[str, dict] = {}
        tot = dict(zuha=0.0, aneeq=0.0, shared=0.0, none=0.0, all=0.0)
        paid = dict(zuha=0.0, aneeq=0.0, shared=0.0, unset=0.0)
        settle = dict(net=0.0, skipped=0.0, aneeq_to_zuha=0.0, zuha_to_aneeq=0.0, big=0.0, aneeq_for_big=0.0)
        unassigned = 0

        def new_row(c):
            return {"cat": c, "zuha": 0.0, "aneeq": 0.0, "shared": 0.0, "none": 0.0, "all": 0.0,
                    "paid": dict(zuha=0.0, aneeq=0.0, shared=0.0, unset=0.0)}

        share = lambda who, x: x if who == "zuha" else x / 2 if who == "shared" else 0.0
        for t in self.month_txns(m):
            cb = self.contrib_of(t)
            if cb:
                amt = abs(t["spend"])
                if cb.get("from") == "aneeq":
                    settle["aneeq_to_zuha"] += amt
                    settle["net"] -= amt
                    if self.proj_of(t):
                        settle["aneeq_for_big"] += amt
                else:
                    settle["zuha_to_aneeq"] += amt
                    settle["net"] += amt
                continue
            pj = self.proj_of(t)
            if pj:
                pay = self.payer_of(t)
                zp = self.tx_z_share(t, pj)
                paid[pay or "unset"] += t["spend"]
                settle["big"] += t["spend"]
                if pay:
                    pz = 1.0 if pay == "zuha" else 0.5 if pay == "shared" else 0.0
                    settle["net"] += (pz - zp) * t["spend"]
                else:
                    settle["skipped"] += t["spend"]
                continue
            c = self.cat_of(t)
            if self.is_excluded(c):
                continue
            p, _ = self.resolve(t)
            k = p or "none"
            if not p:
                unassigned += 1
            row = cats.setdefault(c, new_row(c))
            row[k] += t["spend"]
            row["all"] += t["spend"]
            tot[k] += t["spend"]
            tot["all"] += t["spend"]
            pay = self.payer_of(t)
            row["paid"][pay or "unset"] += t["spend"]
            paid[pay or "unset"] += t["spend"]
            if p and pay:
                settle["net"] += share(pay, t["spend"]) - share(p, t["spend"])
            else:
                settle["skipped"] += t["spend"]
        for c, v in self.plan_for(m).items():
            if c not in cats and float(v or 0) > 0 and not self.is_excluded(c):
                cats[c] = new_row(c)
        return {"cats": list(cats.values()), "tot": tot, "paid": paid, "settle": settle, "unassigned": unassigned}

    def budget_rows(self, m: str) -> list[dict]:
        """One row per budget line / category for the month, ordered by section like the sheet."""
        res = self.compute(m)
        bm, asides = self.plan_for(m), self.asides_for(m)
        order = {k: i for i, (k, _) in enumerate(SECTIONS)}
        rows = []
        for r in res["cats"]:
            planned = float(bm.get(r["cat"]) or 0)
            ad = asides.get(r["cat"], [])
            ad_sum = sum(a["amt"] for a in ad)
            avail = max(0.0, planned - ad_sum)
            g = self.plan["groups"].get(r["cat"]) or ("Other budget lines" if planned else "Not in the budget")
            rows.append({**r, "section": g, "planned": planned, "set_aside": ad_sum,
                         "set_aside_for": ", ".join(f"{a['name']} {a['amt']:,.0f}" for a in ad),
                         "available": avail, "left": avail - r["all"], "owner": self.rules["category"].get(r["cat"]),
                         "_o": order.get(g, 50 if g == "Other budget lines" else 99)})
        rows.sort(key=lambda x: (x["_o"], -x["planned"], -x["all"], x["cat"].lower()))
        return rows

    def section_matrix(self, m: str) -> dict:
        rows: dict[str, dict] = {}
        z = lambda: dict(zuha=0.0, aneeq=0.0, shared=0.0, unset=0.0)

        def add(key, who, amt):
            rows.setdefault(key, z())[who] += amt

        for t in self.month_txns(m):
            if self.contrib_of(t):
                continue
            pay = self.payer_of(t) or "unset"
            pj = self.proj_of(t)
            if pj:
                add("big:" + (pj.get("section") or DEFAULT_SECTION), pay, t["spend"])
                add("proj:" + pj["id"], pay, t["spend"])
                continue
            c = self.cat_of(t)
            if self.is_excluded(c):
                continue
            add(self.section_of(c), pay, t["spend"])
        budget: dict[str, float] = {}
        asides, aside_tot = self.asides_for(m), 0.0
        for c, v in self.plan_for(m).items():
            if self.is_excluded(c):
                continue
            a = sum(x["amt"] for x in asides.get(c, []))
            aside_tot += a
            key = self.section_of(c)
            budget[key] = budget.get(key, 0) + max(0.0, float(v or 0) - a)
        return {"rows": rows, "budget": budget, "aside_tot": aside_tot}

    def settle_rows(self) -> list[dict]:
        run, out = 0.0, []
        for m in self.months():
            s = self.compute(m)["settle"]
            run += s["net"]
            out.append({"month": m, "gross": s["net"] + s["aneeq_to_zuha"] - s["zuha_to_aneeq"],
                        "he_sent": s["aneeq_to_zuha"], "you_sent": s["zuha_to_aneeq"], "net": s["net"],
                        "running": run, "skipped": s["skipped"]})
        return out

    # ---------- importing ----------
    def add_parsed(self, rows: list[dict], statement_id: str, added_by: str, tolerance_days: int = 3) -> tuple[list[dict], int]:
        """Dedupe incoming rows (from a PDF statement or the bank feed) against what's stored.
        Same source: an exact match (bank-feed id, or same day/account/amount for statements).
        Across sources (statement vs bank feed): same account and amount within a few days, because a bank
        feed and a statement can date the same charge a day or two apart. Returns (new transactions, duplicates)."""
        import datetime as _dt
        day = lambda d: _dt.date.fromisoformat(d).toordinal()
        seen: dict[str, int] = {}
        used: set[str] = set()
        new, dup = [], 0
        existing = self.txns
        for r in rows:
            base = "|".join([r["date"], r["desc"], f"{r['amt']:.2f}", r["account"]])
            seen[base] = seen.get(base, 0) + 1
            tid = fnv_id(base + "|" + str(seen[base]))
            spend = round(r["amt"], 2)
            ext = r.get("ext_id")
            rd = day(r["date"])

            def same(t, pool_is_existing):
                if t["id"] in used:
                    return False
                if ext and t.get("ext_id"):
                    return t["ext_id"] == ext
                if t["account"] != r["account"] or abs(t["spend"] - spend) >= 0.005:
                    return t["id"] == tid
                if bool(ext) != bool(t.get("ext_id")):  # one from the feed, one from a statement
                    return pool_is_existing and abs(day(t["date"]) - rd) <= tolerance_days
                return t["date"] == r["date"] or t["id"] == tid

            twin = next((t for t in existing if same(t, True)), None) or next((t for t in new if same(t, False)), None)
            if twin:
                used.add(twin["id"])
                dup += 1
                continue
            t = {"id": tid, "month": r["date"][:7], "date": r["date"], "desc": r["desc"], "mk": merchant_key(r["desc"]),
                 "spend": spend, "category": r.get("category") or "Uncategorized", "account": r["account"],
                 "statement_id": statement_id, "added_by": added_by}
            if ext:
                t["ext_id"] = ext
            new.append(t)
            used.add(tid)
        return new, dup
