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
PAYER_LABEL = {"zuha": "Chase (Zuha)", "aneeq": "Wells Fargo (Aneeq)", "shared": "Joint", "unset": "Payer not set"}
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
    def months(self) -> list[str]:
        return sorted({t["month"] for t in self.txns})

    def month_txns(self, m: str) -> list[dict]:
        return [t for t in self.txns if t.get("month") == m]

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

    def cat_of(self, t: dict) -> str:
        return (t.get("cat_override") or self.pat_cat(t) or self.rules["recat"].get(t.get("mk", ""))
                or self.rules["catmap"].get(t.get("category", "")) or t.get("category") or "Uncategorized")

    def is_excluded(self, cat: str) -> bool:
        v = self.rules["exclude"].get(cat)
        if v is True or v is False:
            return v
        return bool(DEFAULT_EXCLUDE.search(cat or ""))

    def resolve(self, t: dict) -> tuple[str | None, str]:
        if t.get("person"):
            return t["person"], "this transaction only"
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
        return self.rules["payer"].get(t.get("account") or "") or None

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

    def proj_of(self, t: dict) -> dict | None:
        return self.proj_by_id(t.get("project"))

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
        txns = sorted([t for t in self.txns if t.get("project") == p["id"] and not self.contrib_of(t)], key=lambda t: t["date"])
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
    def add_parsed(self, rows: list[dict], statement_id: str, added_by: str) -> tuple[list[dict], int]:
        """Dedupe parsed statement rows against what's stored. Returns (new transactions, skipped duplicates)."""
        seen: dict[str, int] = {}
        used: set[str] = set()
        new, dup = [], 0
        existing = self.txns
        for r in rows:
            base = "|".join([r["date"], r["desc"], f"{r['amt']:.2f}", r["account"]])
            seen[base] = seen.get(base, 0) + 1
            tid = fnv_id(base + "|" + str(seen[base]))
            spend = round(r["amt"], 2)
            twin = next((t for t in existing + new if t["id"] not in used and (t["id"] == tid or (
                t["date"] == r["date"] and t["account"] == r["account"] and abs(t["spend"] - spend) < 0.005))), None)
            if twin:
                used.add(twin["id"])
                dup += 1
                continue
            t = {"id": tid, "month": r["date"][:7], "date": r["date"], "desc": r["desc"], "mk": merchant_key(r["desc"]),
                 "spend": spend, "category": r.get("category") or "Uncategorized", "account": r["account"],
                 "statement_id": statement_id, "added_by": added_by}
            new.append(t)
            used.add(tid)
        return new, dup
