"""Zuha & Aneeq Ledger — Streamlit app.

Run locally:  streamlit run app.py
Secrets (see .streamlit/secrets.toml.example): [auth] Google sign-in, [people] who may sign in,
[google] where the sheet and statements live, [anthropic] for reading PDFs.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid

import pandas as pd
import streamlit as st

from ledger.logic import (learn_key, merchant_key, DEFAULT_EXCLUDE, DEFAULT_SECTION, PAYER_LABEL, PEOPLE, SECTIONS, Ledger, month_label)
from ledger import bankfeed, ui
from ledger.store import GoogleStore, LocalStore, now_iso

# ---- The app's name. Change it here and it updates the page heading, sign-in screen and browser tab. ----
APP_TITLE = "Zuha & Aneeq Ledger"

st.set_page_config(page_title=APP_TITLE, page_icon="💳", layout="wide", initial_sidebar_state="collapsed")

# Who may sign in. [people] in the secrets overrides this.
DEFAULT_PEOPLE = {"zuha": "zuha.m.shaikh@gmail.com", "aneeq": "aneeqc@gmail.com"}

PAGES = ["Overview", "Budget", "Transactions", "Not in budget", "Big expenses", "Settle up", "Statements", "Rules"]
# The three colours used everywhere: purple = Zuha, blue = Aneeq, gold = Shared.
WHO_NAME = {"zuha": "🟣 Zuha", "aneeq": "🔵 Aneeq", "shared": "🟡 Shared"}
WHO_OPTS = [""] + list(WHO_NAME.values())
WHO_KEY = {"": None, "Zuha": "zuha", "Aneeq": "aneeq", "Shared": "shared", **{v: k for k, v in WHO_NAME.items()}}
PAID_NAME = {"zuha": "🟣 Zuha", "aneeq": "🔵 Aneeq", "shared": "🟡 Joint"}
UNSET, NO_ITEM, NO_LINE = "⚪ Not set", "—", "—"
PAYER_OPTS = {"": None, "Zuha (Chase)": "zuha", "Aneeq (Wells Fargo)": "aneeq", "Joint": "shared"}


def money(x: float, cents: bool = False) -> str:
    s = f"${abs(x):,.2f}" if cents else f"${abs(x):,.0f}"
    return ("−" if x < -0.004 else "") + s


def secret(section: str) -> dict:
    """A secrets section as a dict, or {} when it (or the whole secrets file) is missing."""
    try:
        return dict(st.secrets[section]) if section in st.secrets else {}
    except Exception:  # noqa: BLE001 — no secrets file at all
        return {}


# ---------------------------------------------------------------- sign-in
def current_person() -> tuple[str, str]:
    people = {str(v).strip().lower(): k for k, v in (secret("people") or DEFAULT_PEOPLE).items()}
    if not secret("auth"):
        # Open access only for testing on your own computer: LEDGER_LOCAL=1 streamlit run app.py
        if os.environ.get("LEDGER_LOCAL") == "1":
            st.sidebar.warning("Local test mode: no sign-in.")
            return "zuha", "local"
        html(f'<div class="lg-title">{ui.e(APP_TITLE)}</div>')
        st.error("Sign-in isn't set up yet, so the ledger stays locked. Add the [auth] and [auth.google] sections to this app's secrets.")
        st.stop()
    if not st.user.is_logged_in:
        html(f'<div class="lg-title" style="margin-top:8vh">{ui.e(APP_TITLE)}</div><p class="lg-note" style="font-size:15px">Sign in with your Google account to see the household ledger.</p>')
        st.button("Sign in with Google", type="primary", on_click=st.login, args=("google",))
        st.stop()
    email = str(st.user.get("email", "")).lower()
    if email not in people:
        st.error(f"{email} isn't one of the ledger's accounts.")
        st.button("Sign out", on_click=st.logout)
        st.stop()
    return people[email], email


# ---------------------------------------------------------------- data
@st.cache_resource
def get_store():
    if secret("google"):
        return GoogleStore(secret("google"))
    return LocalStore()


@st.cache_data(ttl=60, show_spinner="Loading the ledger…")
def load_data(_store, version: int) -> dict:
    return _store.load()


def ledger_from(d: dict) -> Ledger:
    cfg = d["config"]
    return Ledger(rules=cfg.get("rules") or {}, plan=cfg.get("plan") or {"budgets": {}, "byMonth": {}, "groups": {}},
                  projects=cfg.get("projects") or [], txns=d["txns"], fund_cfg=cfg.get("fund") or {})


def bump():
    st.session_state["v"] = st.session_state.get("v", 0) + 1
    load_data.clear()


def fresh() -> tuple[dict, Ledger]:
    """Read straight from storage before a write, so one person's save doesn't undo the other's."""
    d = get_store().load()
    return d, ledger_from(d)


def save_config(key: str, value):
    get_store().save_config(key, value)
    bump()


DROP = object()  # marks a remembered field to forget


def remember_choices(learn: dict[str, dict], m: str) -> int:
    """Save remembered merchant choices (line / who / big expense). A new choice applies to every month; changing or
    forgetting an existing one only applies from month m on: earlier months keep what they had. Returns charges affected."""
    d, LL = fresh()
    rules = LL.rules
    rules.setdefault("learn", {})
    pinned: dict[str, dict] = {}
    for key, upd in learn.items():
        old = dict(rules["learn"].get(key) or {})
        changing = {f for f, v in upd.items() if f in old and (v is DROP or v != old[f])}
        if changing:
            for t in LL.txns:
                if learn_key(t.get("desc", "")) != key or LL.month_of(t) >= m:
                    continue
                pin = {}
                if {"line", "project"} & changing and not t.get("cat_override") and not t.get("project"):
                    pj = LL.proj_of(t)
                    if pj and old.get("project"):
                        pin["project"] = pj["id"]
                    elif old.get("line"):
                        pin["cat_override"] = LL.cat_of(t)
                if "who" in changing and not t.get("person") and old.get("who"):
                    pin["person"] = old["who"]
                if pin:
                    pinned.setdefault(t["id"], {}).update(pin)
        new = {**old}
        for f, v in upd.items():
            if v is DROP or v in (None, ""):
                new.pop(f, None)
            else:
                new[f] = v
        if new:
            rules["learn"][key] = new
        else:
            rules["learn"].pop(key, None)
    get_store().save_config("rules", rules)
    if pinned:
        for t in d["txns"]:
            if t["id"] in pinned:
                t.update(pinned[t["id"]])
        get_store().save_txns(d["txns"])
    bump()
    return sum(1 for t in LL.txns if learn_key(t.get("desc", "")) in learn and LL.month_of(t) >= m)


def keep_past_plans(plan: dict, months_with_data: list[str], m: str):
    """Before changing the standard plan from month m on, give earlier months that used it their own copy,
    so their budgets don't change after the fact."""
    for k in months_with_data:
        if k < m and k not in plan["byMonth"]:
            plan["byMonth"][k] = dict(plan["budgets"])


def update_txns(changes: dict[str, dict]):
    d, _ = fresh()
    for t in d["txns"]:
        for k, v in changes.get(t["id"], {}).items():
            if v in (None, ""):
                t.pop(k, None)
            else:
                t[k] = v
    get_store().save_txns(d["txns"])
    bump()


# ---------------------------------------------------------------- pages
def html(x: str):
    st.markdown(x, unsafe_allow_html=True)


def close_month_toggle(L: Ledger, m: str, key: str):
    fs = L.fund_settings()
    closed = m in fs["closed"]
    val = st.checkbox(f"All of {month_label(m)}'s statements are in: count its Core and Extras I leftover toward the Extras II fund",
                      value=closed, key=key)
    if val != closed:
        f = fresh()[1].fund_settings()
        f["closed"] = sorted(set(f["closed"]) | {m}) if val else [x for x in f["closed"] if x != m]
        save_config("fund", f)
        st.rerun()


def page_overview(L: Ledger, m: str):
    html(ui.summary(L, m))
    html(ui.sections(L, m))
    html('<div class="lg-h2">Extras II fund</div>')
    html(ui.fund_panel(L, m, compact=True))
    close_month_toggle(L, m, f"close-ov-{m}")


def page_budget(L: Ledger, m: str, person: str = "zuha"):
    html(f'<div class="lg-h2" style="margin-top:4px">Budget check by person, {ui.e(month_label(m))}</div>')
    names = {"zuha": "🟣 Zuha", "aneeq": "🔵 Aneeq"}
    who_label = st.segmented_control("Person", list(names.values()), default=names.get(person, names["zuha"]),
                                     key="budget-person", label_visibility="collapsed") or names.get(person, names["zuha"])
    who = next(k for k, v in names.items() if v == who_label)
    html(ui.person_budget(L, m, who))
    html(ui.budget(L, m))
    own = m in L.plan["byMonth"]
    rows = L.budget_rows(m)
    SEC_LABEL = {k: l for k, l in SECTIONS}
    SEC_KEY = {l: k for k, l in SECTIONS}
    NOT_ON = "Not in the budget"

    exp = st.expander("Edit budget lines: amount, section, whose")
    exp.caption((f"{month_label(m)} has its own plan from your budget sheet; amount changes apply to this month only."
                 if own else f"This month uses your standard plan; amount changes apply from {month_label(m)} on. Earlier months keep their budgets.")
                + " Section and whose apply to every month. Set an amount to 0 to take a line off this month's budget.")
    df = pd.DataFrame([{
        "Section": SEC_LABEL.get(L.plan["groups"].get(r["cat"]), NOT_ON), "Line": r["cat"],
        "Whose": WHO_NAME.get(r["owner"], "") if r["owner"] else "", "Budget": r["planned"], "Spent": r["all"],
    } for r in rows], columns=["Section", "Line", "Whose", "Budget", "Spent"])
    if not df.empty:
        edited = exp.data_editor(df, hide_index=True, width="stretch", key=f"bud-{m}",
                                 column_config={"Section": st.column_config.SelectboxColumn(options=[l for _, l in SECTIONS] + [NOT_ON]),
                                                "Line": st.column_config.TextColumn(disabled=True),
                                                "Whose": st.column_config.SelectboxColumn(options=WHO_OPTS),
                                                "Budget": st.column_config.NumberColumn(format="$%.0f", min_value=0),
                                                "Spent": st.column_config.NumberColumn(format="$%.0f", disabled=True)})
        if exp.button("Save budget changes", type="primary", key="bud-save"):
            _, LL = fresh()
            plan, rules = LL.plan, LL.rules
            if not own:
                keep_past_plans(plan, LL.months(), m)
            tgt = plan["byMonth"][m] if own else plan["budgets"]
            for _, r in edited.iterrows():
                line = r["Line"]
                v = float(r["Budget"] or 0)
                if v:
                    tgt[line] = v
                else:
                    tgt.pop(line, None)
                if r["Section"] in SEC_KEY:
                    plan["groups"][line] = SEC_KEY[r["Section"]]
                else:
                    plan["groups"].pop(line, None)
                who = WHO_KEY.get(r["Whose"] or "")
                if who:
                    rules["category"][line] = who
                else:
                    rules["category"].pop(line, None)
            save_config("plan", plan)
            save_config("rules", rules)
            st.session_state["bud-flash"] = "Budget saved."
            st.rerun()

    with st.expander("＋ Add a budget line"):
        with st.form("add-line", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Name", placeholder="e.g. Gym, Car maintenance, Gifts")
            amt = c2.number_input("Monthly amount", min_value=0.0, step=25.0, format="%.2f")
            c3, c4, c5 = st.columns(3)
            sec = c3.selectbox("Section", [l for _, l in SECTIONS], index=0)
            whose = c4.selectbox("Whose", ["🟡 Shared (50:50)", "🟣 Zuha", "🔵 Aneeq"], index=0,
                                 help="Extras II lines are shared; Core and Extras I lines usually belong to one of you")
            when = c5.selectbox("Applies", [f"From {month_label(m)} on", f"Only {month_label(m)}"])
            ok = st.form_submit_button("Add line", type="primary")
        if ok:
            name = name.strip()
            existing = {x.lower() for x in L.budget_lines()} | {x.lower() for x in L.plan["groups"]}
            if not name:
                st.error("Give the line a name.")
            elif name.lower() in existing:
                st.error(f"There's already a line called “{name}”. Change its amount in Edit budget lines instead.")
            elif L.is_excluded(name):
                st.error("That name looks like a transfer or payment, which isn't counted as spending. Pick another name.")
            else:
                _, LL = fresh()
                plan, rules = LL.plan, LL.rules
                if when.startswith("Only"):
                    if m not in plan["byMonth"]:
                        plan["byMonth"][m] = dict(plan["budgets"])
                    plan["byMonth"][m][name] = float(amt)
                else:
                    keep_past_plans(plan, LL.months(), m)
                    plan["budgets"][name] = float(amt)
                    for k in plan["byMonth"]:
                        if k >= m:
                            plan["byMonth"][k][name] = float(amt)
                plan["groups"][name] = SEC_KEY[sec]
                rules["category"][name] = {"🟡 Shared (50:50)": "shared", "🟣 Zuha": "zuha", "🔵 Aneeq": "aneeq"}[whose]
                save_config("plan", plan)
                save_config("rules", rules)
                st.session_state["bud-flash"] = (f"Added “{name}” ({ui.m(amt)}/month, {sec}). Charges can be put on it from the "
                                                 "Transactions or Not in budget tab.")
                st.rerun()
    if st.session_state.get("bud-flash"):
        st.success(st.session_state.pop("bud-flash"))


def page_transactions(L: Ledger, m: str, person: str):
    html(f'<div class="lg-h2" style="margin-top:4px">Transactions, {ui.e(month_label(m))}</div>')
    show = st.radio("Show", ["All", "Needs a person", "Big expenses", "Money between you", "Not counted"],
                    horizontal=True, key="txfilter")
    q = st.text_input("Search merchant, line or account", key="txsearch").lower()
    proj_label = {p["id"]: "★ " + p["name"] for p in L.projects}
    label_proj = {v: k for k, v in proj_label.items()}
    lines = L.all_categories(m)
    line_opts = [NO_LINE] + lines + list(proj_label.values())
    items = sorted({i["name"] for p in L.projects for i in p.get("items") or []})

    recs, ids = [], []
    deds = L.deduction_txns(m) if L.month_txns(m, with_deductions=False) else []
    if deds:
        html('<p class="lg-note" style="margin:0 0 8px">Also counted this month, without a statement: '
             + " · ".join(f'{ui.e(t["desc"])} {ui.m(t["spend"])}' for t in deds) + '. Change these in Rules → Taken from pay.</p>')
    for t in sorted(L.month_txns(m, with_deductions=False), key=lambda t: t["date"], reverse=True):
        cb, pj, c = L.contrib_of(t), L.proj_of(t), L.cat_of(t)
        ex = L.is_excluded(c) and not cb and not pj
        who, why = L.resolve(t)
        if cb:
            status = f"Money from {PEOPLE[cb['from']]}" + (f" for {pj['name']}" if pj else f" for {t['for_line']}" if t.get("for_line") else "") + " · settle-up"
        elif pj:
            status = f"Big expense: {pj['name']}"
        elif ex:
            status = "Not counted as spending"
        elif L.learned(t).get("line") and not t.get("cat_override"):
            status = "Line remembered · " + why
        else:
            status = why
        orig = L.refund_matches().get(t["id"]) if t["spend"] < 0 else None
        if orig:
            status = f"Refund of the {orig['date']} charge · counts in {month_label(L.month_of(orig))} · " + status
        elif L.shifted(t):
            status = f"Counts in {month_label(L.month_of(t))} (billed for next month) · " + status
        keep = {"Needs a person": not (who or ex or cb or pj), "All": True, "Big expenses": bool(pj and not cb),
                "Money between you": bool(cb), "Not counted": ex}[show]
        if not keep or (q and q not in f"{t['desc']} {c} {t.get('account','')}".lower()):
            continue
        line_val = proj_label.get(pj["id"]) if pj else ((t.get("for_line") or NO_LINE) if cb else c)
        recs.append({"Date": t["date"], "Merchant": t["desc"], "Paid from": PAID_NAME.get(L.payer_of(t) or "", "⚪ not set"),
                     "Amount": t["spend"], "Line": line_val,
                     "Who": (WHO_NAME.get(who, UNSET) if who else UNSET) if not (pj or cb or ex) else NO_ITEM,
                     "Item": t.get("proj_item") or NO_ITEM, "Only this charge": False, "Status": status})
        ids.append(t["id"])
    if not recs:
        st.info("Nothing here.")
        return
    html('<p class="lg-note" style="margin:0 0 8px">Change a charge&#39;s <b>Line</b> or <b>Who</b> and press Save. '
         'Choose ★ in Line to put a charge under a big expense.</p>')
    df = pd.DataFrame(recs)
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key=f"tx-{m}-{show}-{q}",
        column_config={
            "Date": st.column_config.TextColumn(disabled=True, width="small"),
            "Merchant": st.column_config.TextColumn(disabled=True, width="large"),
            "Paid from": st.column_config.TextColumn(disabled=True, width="small"),
            "Amount": st.column_config.NumberColumn(format="dollar", disabled=True, width="small"),
            "Line": st.column_config.SelectboxColumn(options=line_opts, help="Budget line, or ★ a big expense"),
            "Who": st.column_config.SelectboxColumn(options=[UNSET] + WHO_OPTS[1:] + [NO_ITEM], help="Whose budget this counts toward"),
            "Item": st.column_config.SelectboxColumn(options=[NO_ITEM] + items, help="Big-expense item"),
            "Only this charge": st.column_config.CheckboxColumn(help="Tick to change just this charge. Otherwise the choice is remembered for the merchant from now on."),
            "Status": st.column_config.TextColumn(disabled=True)})
    html('<p class="lg-note" style="margin:6px 0">Changes are remembered for the merchant: this month, later months and future statements. '
         'Earlier months keep what they had. To forget a remembered choice, set Line to — or Who to ⚪ Not set. '
         'Tick <b>Only this charge</b> for a one-off exception.</p>')
    if st.button("Save changes", type="primary", key="save-tx"):
        changes: dict[str, dict] = {}
        learn: dict[str, dict] = {}
        byid = {t["id"]: t for t in L.txns}
        for i, (_, new) in enumerate(edited.iterrows()):
            old, t = df.iloc[i], byid[ids[i]]
            ch = {}
            cb = L.contrib_of(t)
            key = learn_key(t["desc"])
            once = bool(new.get("Only this charge"))
            if new["Line"] != old["Line"] and new["Line"]:
                if new["Line"] == NO_LINE:
                    if cb:
                        ch["for_line"] = None
                    elif once:
                        ch["cat_override"] = None
                        ch["project"] = None
                    else:
                        learn.setdefault(key, {}).update(line=DROP, project=DROP)
                        ch["cat_override"] = None
                        ch["project"] = None
                elif new["Line"] in label_proj:
                    if cb or once:
                        ch["project"] = label_proj[new["Line"]]
                        if cb:
                            ch["for_line"] = None
                    else:
                        learn.setdefault(key, {}).update(project=label_proj[new["Line"]], line=DROP)
                        ch["project"] = None
                        ch["cat_override"] = None
                else:
                    ch["proj_item"] = None
                    if cb:
                        ch["for_line"] = new["Line"]
                    elif once:
                        ch["cat_override"] = new["Line"]
                        ch["project"] = "none" if L.proj_of({**t, "project": None}) else None
                    else:
                        learn.setdefault(key, {}).update(line=new["Line"], project=DROP)
                        ch["cat_override"] = None
                        ch["project"] = None
            if new["Who"] != old["Who"] and not cb and new["Who"] != NO_ITEM:
                who = WHO_KEY.get(new["Who"] or "") if new["Who"] != UNSET else None
                if once:
                    ch["person"] = who
                else:
                    learn.setdefault(key, {})["who"] = who if who else DROP
                    ch["person"] = None
            if (new["Item"] or NO_ITEM) != (old["Item"] or NO_ITEM):
                ch["proj_item"] = None if new["Item"] in (None, "", NO_ITEM) else new["Item"]
            if ch:
                changes[t["id"]] = ch
        if changes:
            update_txns(changes)
        n = remember_choices(learn, m) if learn else 0
        if learn or changes:
            st.session_state["flash"] = (f"Saved. Remembered choices updated for {len(learn)} merchant{'s' if len(learn) != 1 else ''}; "
                                         "they apply to future statements too."
                                         if learn else f"Saved {len(changes)} change{'s' if len(changes) != 1 else ''} to just those charges.")
            st.rerun()
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))


def page_unbudgeted(L: Ledger, m: str | None):
    """Counted spending that isn't on any budget line, with a way to put each charge on one."""
    html('<div class="lg-h2" style="margin-top:4px">Not in the budget</div>'
         '<p class="lg-note" style="margin:0 0 10px">Spending that doesn&#39;t fall on any line of your budget sheet '
         '(e.g. Other, Subscriptions, Charity). Pick a budget line under <b>Assign to</b> and press Save.</p>')
    budget_lines = [l for l in L.budget_lines() if not L.is_excluded(l)]
    scope = st.radio("Show", [f"{month_label(m)}" if m else "This month", "All months"], horizontal=True, key="nib-scope")
    months = L.months() if scope == "All months" or not m else [m]
    rows = []
    for mo in months:
        for t in L.month_txns(mo, with_deductions=False):
            if L.contrib_of(t) or L.proj_of(t):
                continue
            c = L.cat_of(t)
            if L.is_excluded(c) or c in budget_lines:
                continue
            rows.append((t, c))
    rows.sort(key=lambda x: x[0]["date"], reverse=True)
    if not rows:
        st.success("Everything counted as spending is on a budget line.")
        return
    total = sum(t["spend"] for t, _ in rows)
    by_cat: dict[str, float] = {}
    by_who: dict[str, float] = {}
    for t, c in rows:
        by_cat[c] = by_cat.get(c, 0) + t["spend"]
        w = L.payer_of(t) or "unset"
        by_who[w] = by_who.get(w, 0) + t["spend"]
    chips = " · ".join(f'{ui.e(c)} <b class="num">{ui.m(v)}</b>' for c, v in sorted(by_cat.items(), key=lambda x: -x[1]))
    paid = " · ".join(f'<span class="dot d-{w}"></span>{ {"zuha": "Zuha", "aneeq": "Aneeq", "shared": "Joint"}.get(w, "Payer not set") } <b class="num">{ui.m(v)}</b>'
                      for w, v in sorted(by_who.items(), key=lambda x: -x[1]))
    html(f'<div class="lg-summary" style="grid-template-columns:minmax(0,1fr) minmax(0,2fr)">'
         f'<div><span class="lg-eyebrow">Not in the budget</span><span class="big num">{ui.m(total)}</span>'
         f'<span class="lg-muted" style="font-size:13px">{len(rows)} charge{"s" if len(rows) != 1 else ""}</span></div>'
         f'<div><span class="lg-eyebrow">By category</span><span style="font-size:14px">{chips}</span>'
         f'<span class="lg-eyebrow" style="margin-top:6px">Paid from</span><span style="font-size:14px">{paid}</span></div></div>')

    KEEP = "— keep as is —"
    df = pd.DataFrame([{"Date": t["date"], "Merchant": t["desc"], "Amount": t["spend"],
                        "Paid from": PAID_NAME.get(L.payer_of(t) or "", UNSET), "Account": t.get("account", ""),
                        "Category now": c, "Assign to": KEEP, "Only this charge": False} for t, c in rows])
    ids = [t["id"] for t, _ in rows]
    ed = st.data_editor(df, hide_index=True, width="stretch", key=f"nib-{scope}-{m}",
                        column_config={"Date": st.column_config.TextColumn(disabled=True, width="small"),
                                       "Merchant": st.column_config.TextColumn(disabled=True, width="large"),
                                       "Amount": st.column_config.NumberColumn(format="dollar", disabled=True, width="small"),
                                       "Paid from": st.column_config.TextColumn(disabled=True, width="small"),
                                       "Account": st.column_config.TextColumn(disabled=True),
                                       "Category now": st.column_config.TextColumn(disabled=True),
                                       "Assign to": st.column_config.SelectboxColumn(options=[KEEP] + budget_lines, help="A line from your budget sheet"),
                                       "Only this charge": st.column_config.CheckboxColumn(help="Tick for a one-off. Otherwise it's remembered for the merchant.")})
    html('<p class="lg-note" style="margin:6px 0">Assignments are remembered for the merchant from this month on and for future statements; '
         'earlier months keep what they had. Tick <b>Only this charge</b> for a one-off.</p>')
    if st.button("Save assignments", type="primary", key="nib-save"):
        byid = {t["id"]: t for t in L.txns}
        learn, changes = {}, {}
        for i, (_, r) in enumerate(ed.iterrows()):
            if r["Assign to"] in (None, "", KEEP):
                continue
            t = byid[ids[i]]
            if bool(r.get("Only this charge")):
                changes[t["id"]] = {"cat_override": r["Assign to"]}
            else:
                learn.setdefault(learn_key(t["desc"]), {}).update(line=r["Assign to"], project=DROP)
                if t.get("cat_override"):
                    changes[t["id"]] = {"cat_override": None}
        if changes:
            update_txns(changes)
        start = m if (m and scope != "All months") else (min(L.months()) if L.months() else "0000-00")
        n = remember_choices(learn, start) if learn else 0
        if learn or changes:
            st.session_state["nib-flash"] = (f"Assigned and remembered for {len(learn)} merchant{'s' if len(learn) != 1 else ''}; future statements will follow it."
                                             if learn else f"Assigned {len(changes)} charge{'s' if len(changes) != 1 else ''}.")
            st.rerun()
    if st.session_state.get("nib-flash"):
        st.success(st.session_state.pop("nib-flash"))


def page_big(L: Ledger, m: str | None = None):
    html('<div class="lg-h2" style="margin-top:4px">Extras II fund</div><p class="lg-note" style="margin:0 0 10px">Each month the fund gets that month&#39;s '
         'Extras II budget, plus whatever was left on Core and Extras I once the month is closed. Everyday Extras II spending and big expenses '
         'come out of it. Unspent money stays in the fund; a negative balance is paid back by future months.</p>')
    html(ui.fund_panel(L, m))
    if m:
        close_month_toggle(L, m, f"close-big-{m}")
    with st.expander("Fund settings: start, top-ups, closed months"):
        fs = L.fund_settings()
        c1, c2 = st.columns(2)
        start = c1.text_input("Fund starts (YYYY-MM)", value=fs["start"], key="f-start")
        opening = c2.number_input("Balance at the start", value=float(fs["opening"] or 0), step=50.0, key="f-open")
        st.markdown("**Top-ups** (money put into the fund from outside the monthly budget, e.g. Aneeq's Roth). Leave Month blank for planned ones; they count in the outlook only.")
        tdf = pd.DataFrame([{"Month": t.get("month") or "", "Whose money": {"zuha": "🟣 Zuha", "aneeq": "🔵 Aneeq"}.get(t.get("who"), ""),
                             "Amount": float(t.get("amount") or 0), "Note": t.get("note", "")} for t in fs["topups"]],
                           columns=["Month", "Whose money", "Amount", "Note"])
        ted = st.data_editor(tdf, hide_index=True, width="stretch", num_rows="dynamic", key="f-tops",
                             column_config={"Month": st.column_config.TextColumn(help="YYYY-MM, or blank if not yet received"),
                                            "Whose money": st.column_config.SelectboxColumn(options=["🟣 Zuha", "🔵 Aneeq"]),
                                            "Amount": st.column_config.NumberColumn(format="$%.2f")})
        closed = st.multiselect("Closed months (all statements in)", L.months(), default=[x for x in fs["closed"] if x in L.months()],
                                format_func=month_label, key="f-closed")
        if st.button("Save fund settings", type="primary", key="f-save"):
            import re as _re
            if not _re.fullmatch(r"\d{4}-\d{2}", start.strip()):
                st.error("Start month must look like 2026-09.")
            else:
                save_config("fund", {"start": start.strip(), "opening": float(opening or 0), "closed": sorted(closed),
                                     "topups": [{"month": str(r["Month"] or "").strip(), "who": {"🟣 Zuha": "zuha", "🔵 Aneeq": "aneeq"}.get(r["Whose money"]),
                                                 "amount": float(r["Amount"] or 0), "note": str(r["Note"] or "")}
                                                for _, r in ted.iterrows() if float(r["Amount"] or 0)]})
                st.success("Saved.")
                st.rerun()

    html('<div class="lg-h2">Big expenses</div><p class="lg-note" style="margin:0 0 12px">Paid from the Extras II fund and split 50:50 unless you change it. '
         'Tag a charge to one from Transactions by choosing ★ in the Line column.</p>')
    for p in L.projects:
        stt = L.proj_stats(p)
        html(ui.big_card(L, p))
        with st.expander(f"Edit {p['name']}"):

            items = pd.DataFrame([{"Item": i["name"], "Whose": WHO_NAME.get(i.get("who"), "") if i.get("who") else "",
                                   "Estimated": float(i.get("est") or 0), "Spent so far": stt["by_item"].get(i["name"], 0.0)}
                                  for i in p.get("items") or []], columns=["Item", "Whose", "Estimated", "Spent so far"])
            ed = st.data_editor(items[["Item", "Whose", "Estimated"]], hide_index=True, width="stretch", num_rows="dynamic", key=f"items-{p['id']}",
                                column_config={"Whose": st.column_config.SelectboxColumn(options=WHO_OPTS, help="Blank = project split"),
                                               "Estimated": st.column_config.NumberColumn(format="$%.0f")})

            c1, c2, c3 = st.columns(3)
            split_opts = {"50:50": "even", "Custom": "custom", "All Zuha": "zuha", "All Aneeq": "aneeq"}
            cur_split = p.get("split") if p.get("split") in split_opts.values() else "even"
            split = c1.selectbox("Split", list(split_opts), index=list(split_opts.values()).index(cur_split), key=f"split-{p['id']}")
            zpct = c3.number_input("Zuha's share %", min_value=0, max_value=100, value=int(float(p.get("zuha_pct") or 50)),
                                   key=f"zpct-{p['id']}", disabled=split_opts[split] != "custom")
            sec_names = [l for _, l in SECTIONS]
            cur = next((l for k, l in SECTIONS if k == (p.get("section") or DEFAULT_SECTION)), "Extras II")
            sec = c2.selectbox("Counts under", sec_names, index=sec_names.index(cur), key=f"sec-{p['id']}")
            if st.button("Save changes", key=f"save-{p['id']}", type="primary"):
                projects = fresh()[1].projects
                tgt = next(x for x in projects if x["id"] == p["id"])
                tgt["items"] = [{"name": str(r["Item"]), "est": float(r["Estimated"] or 0),
                                 **({"who": WHO_KEY[r["Whose"]]} if r.get("Whose") else {})}
                                for _, r in ed.iterrows() if str(r["Item"] or "").strip()]
                tgt["split"] = split_opts[split]
                if split_opts[split] == "custom":
                    tgt["zuha_pct"] = int(zpct)
                else:
                    tgt.pop("zuha_pct", None)
                tgt["section"] = next(k for k, l in SECTIONS if l == sec)
                save_config("projects", projects)
                st.success("Saved.")
                st.rerun()

    with st.form("new-project", clear_on_submit=True):
        name = st.text_input("New big expense")
        if st.form_submit_button("Add big expense") and name.strip():
            projects = fresh()[1].projects
            pid = "-".join(w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in name).split()) or "big"
            while any(x["id"] == pid for x in projects):
                pid += "-2"
            projects.append({"id": pid, "name": name.strip(), "items": [], "funding": []})
            save_config("projects", projects)
            st.rerun()


def page_settle(L: Ledger, m: str | None = None):
    html(ui.settle(L, m))


# ---------------------------------------------------------------- bank sync (SimpleFIN)
def feed_urls() -> list[str]:
    sec = secret("simplefin")
    urls = sec.get("access_urls") or ([sec["access_url"]] if sec.get("access_url") else [])
    return [str(u) for u in urls if u]


def run_sync(person: str) -> tuple[str, list[str]]:
    """Pull recent transactions from every connected bank and add the ones not already in the ledger."""
    store = get_store()
    d, LL = fresh()
    sync = d["config"].get("sync") or {}
    start, end = bankfeed.window(sync.get("last"), time.time())
    rows, errs = [], []
    for u in feed_urls():
        try:
            data = bankfeed.fetch(u, start, end)
        except bankfeed.FeedError as e:
            errs.append(str(e))
            continue
        except Exception as e:  # noqa: BLE001 — network trouble: report it, keep going
            errs.append(f"Couldn't reach SimpleFIN ({type(e).__name__}). Try again later.")
            continue
        errs += bankfeed.messages(data)
        rows += bankfeed.to_rows(data, LL.accounts())
    new, dup = LL.add_parsed(rows, "bank-sync", person)
    # Charges you categorized by hand before (one at a time) keep that line when they come in from the bank.
    prior: dict[str, str] = {}
    for t in sorted(LL.txns, key=lambda t: t["date"]):
        if t.get("cat_override"):
            prior[learn_key(t["desc"])] = t["cat_override"]
    for t in new:
        k = learn_key(t["desc"])
        if k in prior and not LL.learned(t).get("line"):
            t["cat_override"] = prior[k]
    # Categorize only what the household's own rules don't already cover.
    unknown = [t for t in new if t["category"] == "Uncategorized" and LL.cat_of(t) == "Uncategorized" and not LL.contrib_of(t)]
    key, model = secret("anthropic").get("api_key"), secret("anthropic").get("model", "claude-sonnet-5-5")
    if unknown and key:
        try:
            from ledger.parse import categorize
            done = categorize([{"desc": t["desc"], "amt": t["spend"], "account": t["account"], "category": t["category"]} for t in unknown],
                              LL, key, model)
            for t, r in zip(unknown, done):
                t["category"] = r["category"]
        except Exception:  # noqa: BLE001 — leave them for the Not in budget tab
            errs.append("Claude couldn't categorize some new charges; they're on the Not in budget tab.")
    # New accounts: Chase is Zuha's, Wells Fargo is Aneeq's.
    rules, changed = LL.rules, False
    for a in {t["account"] for t in new}:
        if not rules["payer"].get(a):
            who = "zuha" if "chase" in a.lower() else "aneeq" if "wells" in a.lower() else None
            if who:
                rules["payer"][a] = who
                changed = True
    if new:
        store.save_txns(d["txns"] + new)
    if changed:
        store.save_config("rules", rules)
    store.save_config("sync", {"last": end, "at": now_iso(), "by": person, "added": len(new), "skipped": dup, "errors": errs[:10]})
    bump()
    msg = f"Bank sync added {len(new)} new transaction{'s' if len(new) != 1 else ''}" + (f" ({dup} already in the ledger)" if dup else "") + "."
    return msg, errs


def bank_sync_panel(d: dict, person: str):
    urls = feed_urls()
    sync = d["config"].get("sync") or {}
    html('<div class="lg-h2" style="margin-top:4px">Bank sync</div>')
    if urls:
        last = sync.get("at")
        info = (f"Last synced {str(last)[:16].replace('T', ' ')} by {PEOPLE.get(sync.get('by'), sync.get('by', ''))}: "
                f"{sync.get('added', 0)} new, {sync.get('skipped', 0)} already here." if last else "Not synced yet.")
        html(f'<p class="lg-note" style="margin:0 0 8px">{ui.e(info)} The app also syncs by itself when someone opens it '
             'and the last sync is more than 20 hours old. Banks update once a day.</p>')
        for e_ in sync.get("errors") or []:
            st.warning(e_)
        recent = sync.get("last") and time.time() - float(sync["last"]) < 15 * 60
        if st.button("Sync banks now", type="primary", key="sync-now", disabled=bool(recent),
                     help="Available again 15 minutes after the last sync" if recent else None):
            with st.spinner("Getting new transactions from your banks…"):
                msg, errs = run_sync(person)
            st.session_state["st-flash"] = msg
            st.rerun()
    else:
        html('<p class="lg-note" style="margin:0 0 8px">Connect Chase and Wells Fargo through SimpleFIN Bridge so new '
             'transactions come in automatically. PDF uploads below keep working either way.</p>')
    with st.expander("Connect banks" if not urls else "Connect another SimpleFIN account"):
        st.markdown("1. In SimpleFIN Bridge, link your banks, then under **Apps** create a new connection and copy the **setup token**.\n"
                    "2. Paste it here and press **Connect**. Each token works once.")
        tok = st.text_input("Setup token", type="password", key="sfin-token")
        if st.button("Connect", key="sfin-connect") and tok.strip():
            try:
                access = bankfeed.claim(tok)
            except bankfeed.FeedError as e:
                st.error(str(e))
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't reach SimpleFIN ({type(e).__name__}). Try again.")
            else:
                all_urls = urls + [access]
                block = ("[simplefin]\n" + (f'access_url = "{access}"' if len(all_urls) == 1
                                             else "access_urls = [\n" + ",\n".join(f'  "{u}"' for u in all_urls) + "\n]"))
                st.success("Connected. Last step: save this in the app's secrets (⋮ → Settings → Secrets), "
                           "replacing any existing [simplefin] section, then reboot the app. Keep it private: it reads your bank transactions.")
                st.code(block, language="toml")


def page_statements(L: Ledger, d: dict, person: str):
    bank_sync_panel(d, person)
    html('<div class="lg-h2">Statements</div>')
    api_key = secret("anthropic").get("api_key")
    model = secret("anthropic").get("model", "claude-sonnet-5-5")
    html('<p class="lg-note" style="margin:0 0 10px">Upload PDF statements from Chase, Wells Fargo or any other card. '
         'Claude reads each one; you check the totals and pick whose account it is, then add it to the ledger. '
         'The original PDF is saved to the shared Drive folder.</p>')
    files = st.file_uploader("Bank or card statement PDFs", type=["pdf"], accept_multiple_files=True, key="uploader")
    saved = d.get("statements") or []
    by_hash = {s_.get("file_hash"): s_ for s_ in saved if s_.get("file_hash")}
    if files and st.button("Read statements", type="primary", disabled=not api_key):
        from ledger.parse import read_statement
        pend = st.session_state.setdefault("pending", {})
        pend_hashes = {p_.get("hash") for p_ in pend.values()}
        for f in files:
            pdf = f.getvalue()
            h = hashlib.sha256(pdf).hexdigest()
            if h in by_hash:  # exact same file: don't send it to Claude again
                s_ = by_hash[h]
                st.info(f"{f.name} was already added on {str(s_.get('uploaded_at', ''))[:10]} by "
                        f"{PEOPLE.get(s_.get('uploaded_by'), s_.get('uploaded_by', ''))} ({s_.get('account', '')}, "
                        f"{s_.get('period_start', '')} to {s_.get('period_end', '')}), so it wasn't read again.")
                continue
            if h in pend_hashes:
                st.info(f"{f.name} is already waiting below to be added.")
                continue
            with st.spinner(f"Reading {f.name}… this usually takes under a minute"):
                try:
                    pend[f.name] = {"pdf": pdf, "hash": h, "res": read_statement(pdf, L, api_key, model), "name": f.name}
                    pend_hashes.add(h)
                except Exception as e:  # noqa: BLE001 — show the reason and keep going with the others
                    st.error(f"{f.name}: {e}")
    if not api_key:
        st.warning("Add an Anthropic API key under [anthropic] in the app's secrets to read statements.")

    for name, p in list(st.session_state.get("pending", {}).items()):
        res = p["res"]
        rows = res["rows"]
        out = sum(r["amt"] for r in rows if r["amt"] > 0)
        back = -sum(r["amt"] for r in rows if r["amt"] < 0)
        with st.container(border=True):
            st.markdown(f"**{res['account']}** · {res.get('start') or '?'} to {res.get('end') or '?'} · {len(rows)} transactions · `{name}`")
            tot = res.get("totals") or {}

            def chk(mine, theirs, label):
                if isinstance(theirs, (int, float)) and theirs > 0:
                    return (f":green[✓ {label} {money(mine, True)} matches the statement]" if abs(mine - theirs) < .01
                            else f":orange[{label} {money(mine, True)} vs {money(theirs, True)} on the statement]")
                return f"{label} {money(mine, True)}"
            st.markdown(chk(out, tot.get("purchases"), "Money out") + " · " + chk(back, tot.get("credits"), "Payments & credits"))
            preview_new, preview_dup = L.add_parsed(rows, "preview", person)
            same_period = [s_ for s_ in saved if s_.get("account") == res["account"] and res.get("start") and res.get("end")
                           and s_.get("period_start") == res.get("start") and s_.get("period_end") == res.get("end")]
            if same_period:
                st.warning(f"This looks like a statement already added on {str(same_period[0].get('uploaded_at', ''))[:10]} "
                           f"(same account and dates). Only charges not already in the ledger will be added.")
            if not preview_new:
                st.markdown(f":green[All {len(rows)} transactions are already in the ledger. Nothing new to add.]")
            elif preview_dup:
                st.markdown(f"**{len(preview_new)} new** transactions will be added; {preview_dup} already in the ledger will be skipped.")
            else:
                st.markdown(f"**{len(preview_new)} new** transactions will be added.")
            cur = L.rules["payer"].get(res["account"])
            labels = list(PAYER_OPTS)
            idx = next((i for i, (k, v) in enumerate(PAYER_OPTS.items()) if v == cur), 0)
            payer = st.selectbox("Whose account is this?", labels, index=idx, key=f"payer-{name}")
            c1, c2 = st.columns([1, 4])
            if c1.button("Add to ledger", key=f"add-{name}", type="primary", disabled=not PAYER_OPTS[payer] or not preview_new):
                store = get_store()
                dd, LL = fresh()
                sid = uuid.uuid4().hex[:12]
                new, dup = LL.add_parsed(rows, sid, person)
                meta = store.add_statement({"id": sid, "filename": name, "account": res["account"],
                                            "period_start": res.get("start") or "", "period_end": res.get("end") or "",
                                            "uploaded_by": person, "uploaded_at": now_iso(), "n_added": len(new),
                                            "n_skipped": dup, "file_hash": p.get("hash", "")}, p["pdf"])
                store.save_txns(dd["txns"] + new)
                if LL.rules["payer"].get(res["account"]) != PAYER_OPTS[payer]:
                    LL.rules["payer"][res["account"]] = PAYER_OPTS[payer]
                    store.save_config("rules", LL.rules)
                st.session_state["pending"].pop(name, None)
                bump()
                st.session_state["st-flash"] = (f"Added {len(new)} transactions" + (f", skipped {dup} already in the ledger" if dup else "")
                                                + f" from {meta['filename']}.")
                st.rerun()
            if c2.button("Discard", key=f"drop-{name}"):
                st.session_state["pending"].pop(name, None)
                st.rerun()

    if st.session_state.get("st-flash"):
        st.success(st.session_state.pop("st-flash"))
    sts = sorted(d.get("statements") or [], key=lambda s: s.get("uploaded_at", ""), reverse=True)
    if sts:
        st.markdown("**Saved statements**")
        for s in sts:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"{s.get('account','')} · {s.get('period_start','')} to {s.get('period_end','')} · "
                        f"{s.get('n_added','?')} added · uploaded by {PEOPLE.get(s.get('uploaded_by'), s.get('uploaded_by',''))} "
                        f"on {str(s.get('uploaded_at',''))[:10]} · `{s.get('filename','')}`")
            key = f"pdf-{s['id']}"
            if c2.button("Get PDF", key=f"get-{s['id']}"):
                st.session_state[key] = get_store().get_pdf(s)
            if st.session_state.get(key):
                c2.download_button("Download", st.session_state[key], file_name=s.get("filename") or "statement.pdf",
                                   mime="application/pdf", key=f"dl-{s['id']}")


def page_rules(L: Ledger, d: dict):
    html('<div class="lg-h2" style="margin-top:4px">Rules</div>')
    rules = L.rules
    st.caption("Colours: 🟣 Zuha · 🔵 Aneeq · 🟡 Shared. A charge's person comes from the first match: a one-off choice, "
               "a remembered merchant, an older merchant rule, an account rule, then the line's owner.")

    st.markdown("**Accounts**")
    accts = sorted(set(L.accounts()) | set(rules["payer"]))
    inv = {v: k for k, v in PAYER_OPTS.items()}
    adf = pd.DataFrame([{"Account": a, "Paid by": inv.get(rules["payer"].get(a), "")} for a in accts], columns=["Account", "Paid by"])
    aed = st.data_editor(adf, hide_index=True, width="stretch", key="r-acct",
                         column_config={"Account": st.column_config.TextColumn(disabled=True),
                                        "Paid by": st.column_config.SelectboxColumn(options=list(PAYER_OPTS))})

    st.markdown("**Money between you** (incoming or outgoing transfers whose description contains this text)")
    cdf = pd.DataFrame([{"Description contains": c["match"], "From": PEOPLE[c["from"]]} for c in rules["contrib"]],
                       columns=["Description contains", "From"])
    ced = st.data_editor(cdf, hide_index=True, width="stretch", num_rows="dynamic", key="r-contrib",
                         column_config={"From": st.column_config.SelectboxColumn(options=["Aneeq", "Zuha"])})

    lines = L.budget_lines()
    st.markdown("**Remembered merchants** (set from the Transactions or Not in budget tab; these win over every other rule). "
                "Removing one here forgets it for every month; to stop it only from a month on, set its Line to — on Transactions.")
    lrn = rules.get("learn") or {}
    lrdf = pd.DataFrame([{"Merchant": k, "Line": v.get("line", "") or ("★ " + pn) if (pn := {p["id"]: p["name"] for p in L.projects}.get(v.get("project"))) else v.get("line", ""),
                          "Who": WHO_NAME.get(v.get("who"), "")} for k, v in sorted(lrn.items())],
                        columns=["Merchant", "Line", "Who"])
    lred = st.data_editor(lrdf, hide_index=True, width="stretch", num_rows="dynamic", key="r-learn",
                          column_config={"Merchant": st.column_config.TextColumn(disabled=False),
                                         "Line": st.column_config.SelectboxColumn(options=[""] + L.all_categories() + ["★ " + p["name"] for p in L.projects]),
                                         "Who": st.column_config.SelectboxColumn(options=WHO_OPTS)})

    st.markdown("**Always counts toward a big expense** (descriptions matching this go to the big expense, even payments to PayPal)")
    pnames = {p["id"]: p["name"] for p in L.projects}
    prdf = pd.DataFrame([{"Description matches": x["match"], "Big expense": pnames.get(x["project"], "")} for x in L.proj_rules()],
                        columns=["Description matches", "Big expense"])
    pred = st.data_editor(prdf, hide_index=True, width="stretch", num_rows="dynamic", key="r-proj",
                          column_config={"Description matches": st.column_config.TextColumn(help="Words from the description, e.g. wayfair; use | between alternatives"),
                                         "Big expense": st.column_config.SelectboxColumn(options=list(pnames.values()))})

    st.markdown("**Billed for next month** (charges from these merchants on or after the given day count in the following month)")
    sdf = pd.DataFrame([{"Merchant contains": x["match"], "From day": int(x.get("from_day") or 20)} for x in L.shift_rules()],
                       columns=["Merchant contains", "From day"])
    shed = st.data_editor(sdf, hide_index=True, width="stretch", num_rows="dynamic", key="r-shift",
                          column_config={"Merchant contains": st.column_config.TextColumn(help="Lowercase words from the merchant name, e.g. ota scuba swim"),
                                         "From day": st.column_config.NumberColumn(min_value=1, max_value=31, step=1)})

    st.markdown("**Taken from pay** (counted as spent every month without a statement, e.g. insurance deducted from a paycheck)")
    ddf = pd.DataFrame([{"Line": x["line"], "Whose pay": PEOPLE.get(x.get("who") or "zuha"), "Amount": float(x["amount"]) if x.get("amount") else None}
                        for x in L.deductions()], columns=["Line", "Whose pay", "Amount"])
    ded = st.data_editor(ddf, hide_index=True, width="stretch", num_rows="dynamic", key="r-ded",
                         column_config={"Line": st.column_config.SelectboxColumn(options=L.budget_lines()),
                                        "Whose pay": st.column_config.SelectboxColumn(options=["Zuha", "Aneeq"]),
                                        "Amount": st.column_config.NumberColumn(format="$%.2f", help="Blank = that month's budget for the line")})

    st.markdown("**Store rules** (any charge naming the store goes to the line)")
    pdf = pd.DataFrame([{"Store": r.get("label") or r["match"], "Matches": r["match"], "Except": r.get("not", ""), "Line": r["cat"]}
                        for r in rules["patcat"]], columns=["Store", "Matches", "Except", "Line"])
    ped = st.data_editor(pdf, hide_index=True, width="stretch", num_rows="dynamic", key="r-pat",
                         column_config={"Line": st.column_config.SelectboxColumn(options=lines),
                                        "Matches": st.column_config.TextColumn(help="Lowercase word(s), e.g. costco or (walmart|wm supercenter)"),
                                        "Except": st.column_config.TextColumn(help="e.g. costco gas")})

    st.markdown("**Merchant rules**")
    mks = sorted(set(rules["merchant"]) | set(rules["recat"]))
    mdf = pd.DataFrame([{"Merchant": k, "Line": rules["recat"].get(k, ""), "Counts toward": WHO_NAME.get(rules["merchant"].get(k), "") if rules["merchant"].get(k) else ""}
                        for k in mks], columns=["Merchant", "Line", "Counts toward"])
    med = st.data_editor(mdf, hide_index=True, width="stretch", num_rows="dynamic", key="r-merch",
                         column_config={"Line": st.column_config.SelectboxColumn(options=[""] + L.all_categories()),
                                        "Counts toward": st.column_config.SelectboxColumn(options=WHO_OPTS)})

    st.markdown("**Budget lines**")
    ldf = pd.DataFrame([{"Line": c, "Whose": WHO_NAME.get(rules["category"].get(c), "") if rules["category"].get(c) else "",
                         "Counted as spending": not L.is_excluded(c)} for c in L.all_categories()],
                       columns=["Line", "Whose", "Counted as spending"])
    led = st.data_editor(ldf, hide_index=True, width="stretch", key="r-lines",
                         column_config={"Line": st.column_config.TextColumn(disabled=True),
                                        "Whose": st.column_config.SelectboxColumn(options=WHO_OPTS)})

    if st.button("Save rules", type="primary"):
        r = fresh()[1].rules
        for _, x in aed.iterrows():
            if PAYER_OPTS.get(x["Paid by"]):
                r["payer"][x["Account"]] = PAYER_OPTS[x["Paid by"]]
            else:
                r["payer"].pop(x["Account"], None)
        r["contrib"] = [{"match": str(x["Description contains"]), "from": x["From"].lower(),
                         "to": "zuha" if x["From"] == "Aneeq" else "aneeq"}
                        for _, x in ced.iterrows() if str(x["Description contains"] or "").strip() and x["From"]]
        old_not = {str(o.get("not", "")).lower(): o.get("notLabel") for o in r.get("patcat") or [] if o.get("not")}
        r["patcat"] = [{"match": str(x["Matches"]).lower(), "cat": x["Line"], "label": x["Store"] or x["Matches"],
                        **({"not": str(x["Except"]).lower(), "notLabel": old_not.get(str(x["Except"]).lower()) or x["Except"]}
                           if str(x["Except"] or "").strip() else {})}
                       for _, x in ped.iterrows() if str(x["Matches"] or "").strip() and x["Line"]]
        r["deductions"] = [{"line": x["Line"], "who": WHO_KEY.get(x["Whose pay"] or "Zuha") or "zuha",
                            **({"amount": float(x["Amount"])} if x["Amount"] == x["Amount"] and x["Amount"] else {})}
                           for _, x in ded.iterrows() if x["Line"]]
        name_id = {v: k for k, v in pnames.items()}
        r["projrule"] = [{"match": str(x["Description matches"]).strip().lower(), "project": name_id[x["Big expense"]]}
                         for _, x in pred.iterrows() if str(x["Description matches"] or "").strip() and x["Big expense"] in name_id]
        r["shift"] = [{"match": str(x["Merchant contains"]).strip().lower(), "from_day": int(x["From day"] or 20)}
                      for _, x in shed.iterrows() if str(x["Merchant contains"] or "").strip() and x["From day"] == x["From day"]]
        r["learn"] = {}
        for _, x in lred.iterrows():
            k = str(x["Merchant"] or "").strip().lower()
            if k and (x["Line"] or x["Who"]):
                star = {"★ " + p["name"]: p["id"] for p in L.projects}
                line = {"project": star[x["Line"]]} if x["Line"] in star else ({"line": x["Line"]} if x["Line"] else {})
                r["learn"][k] = {**line, **({"who": WHO_KEY[x["Who"]]} if x["Who"] else {})}
        r["merchant"], r["recat"] = {}, {}
        for _, x in med.iterrows():
            k = str(x["Merchant"] or "").strip()
            if not k:
                continue
            if x["Line"]:
                r["recat"][k] = x["Line"]
            if x["Counts toward"]:
                r["merchant"][k] = WHO_KEY[x["Counts toward"]]
        for _, x in led.iterrows():
            if x["Whose"]:
                r["category"][x["Line"]] = WHO_KEY[x["Whose"]]
            else:
                r["category"].pop(x["Line"], None)
            default_ex = bool(DEFAULT_EXCLUDE.search(x["Line"]))
            if bool(x["Counted as spending"]) == (not default_ex):
                r["exclude"].pop(x["Line"], None)
            else:
                r["exclude"][x["Line"]] = not bool(x["Counted as spending"])
        save_config("rules", r)
        st.success("Rules saved.")
        st.rerun()


def page_setup(d: dict):
    html('<div class="lg-h2" style="margin-top:4px">Bring in your current ledger</div>')
    st.write("The ledger is empty. Upload `seed_data.json` (exported from the old ledger page) to start with your "
             "budget, rules, big expenses and the transactions already sorted.")
    f = st.file_uploader("seed_data.json", type=["json"])
    if f and st.button("Import", type="primary"):
        seed = json.loads(f.getvalue())
        store = get_store()
        rename = {"catOverride": "cat_override", "projItem": "proj_item", "forLine": "for_line", "movedFrom": "moved_from"}
        txns = [{rename.get(k, k): v for k, v in t.items()} for t in seed.get("transactions", [])]
        store.save_config("rules", seed.get("rules") or {})
        store.save_config("plan", seed.get("plan") or {})
        store.save_config("projects", seed.get("projects") or [])
        store.save_txns(txns)
        bump()
        st.success(f"Imported {len(txns)} transactions.")
        st.rerun()


# ---------------------------------------------------------------- main
def main():
    html(ui.CSS)
    person, email = current_person()
    store = get_store()
    d = load_data(store, st.session_state.get("v", 0))
    if feed_urls() and not st.session_state.get("autosync-done"):
        st.session_state["autosync-done"] = True
        last = float((d["config"].get("sync") or {}).get("last") or 0)
        if time.time() - last > 20 * 3600:
            with st.spinner("Checking your banks for new transactions…"):
                try:
                    msg, _ = run_sync(person)
                    st.toast(msg)
                except Exception:  # noqa: BLE001 — never block the app on the feed
                    pass
            d = load_data(store, st.session_state.get("v", 0))
    L = ledger_from(d)
    months = L.months()

    top_l, top_r = st.columns([3, 1], vertical_alignment="bottom")
    top_l.markdown(ui.header(person, APP_TITLE), unsafe_allow_html=True)
    m = top_r.selectbox("Month", list(reversed(months)), format_func=month_label, key="month") if months else None
    top_r.button("＋ Upload statement", type="primary", width="stretch", key="go-upload",
                 on_click=lambda: st.session_state.update(page="Statements"))
    page = st.segmented_control("Page", PAGES, default="Overview", key="page", label_visibility="collapsed") or "Overview"

    with st.sidebar:
        st.markdown(f"**{PEOPLE.get(person, person)}**  \n{email if email != 'local' else 'Local test mode'}")
        if st.button("Refresh data", width="stretch"):
            bump()
            st.rerun()
        if email != "local":
            st.button("Sign out", on_click=st.logout, width="stretch")
        if store.kind == "local":
            st.caption("Storage: this computer only (Google isn't configured).")

    if not d["txns"] and not d["config"]:
        page_setup(d)
        if page != "Statements":
            return
    if page == "Statements":
        page_statements(L, d, person)
    elif page == "Rules":
        page_rules(L, d)
    elif page == "Big expenses":
        page_big(L, m)
    elif page == "Settle up":
        page_settle(L, m)
    elif not m:
        st.info("Add a statement on the Statements page to get started.")
    elif page == "Overview":
        page_overview(L, m)
    elif page == "Budget":
        page_budget(L, m, person)
    elif page == "Not in budget":
        page_unbudgeted(L, m)
    elif page == "Transactions":
        page_transactions(L, m, person)


main()
