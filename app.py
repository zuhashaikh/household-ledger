"""Zuha & Aneeq Ledger — Streamlit app.

Run locally:  streamlit run app.py
Secrets (see .streamlit/secrets.toml.example): [auth] Google sign-in, [people] who may sign in,
[google] where the sheet and statements live, [anthropic] for reading PDFs.
"""
from __future__ import annotations

import json
import os
import uuid

import pandas as pd
import streamlit as st

from ledger.logic import (learn_key, DEFAULT_EXCLUDE, DEFAULT_SECTION, PAYER_LABEL, PEOPLE, SECTIONS, Ledger, month_label)
from ledger import ui
from ledger.store import GoogleStore, LocalStore, now_iso

# ---- The app's name. Change it here and it updates the page heading, sign-in screen and browser tab. ----
APP_TITLE = "Zuha & Aneeq Ledger"

st.set_page_config(page_title=APP_TITLE, page_icon="💳", layout="wide", initial_sidebar_state="collapsed")

# Who may sign in. [people] in the secrets overrides this.
DEFAULT_PEOPLE = {"zuha": "zuha.m.shaikh@gmail.com", "aneeq": "aneeqc@gmail.com"}

PAGES = ["Overview", "Budget", "Transactions", "Big expenses", "Settle up", "Statements", "Rules"]
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
                  projects=cfg.get("projects") or [], txns=d["txns"])


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


def page_overview(L: Ledger, m: str):
    html(ui.summary(L, m))
    html(ui.sections(L, m))


def page_budget(L: Ledger, m: str):
    html(ui.budget(L, m))
    own = m in L.plan["byMonth"]
    rows = L.budget_rows(m)
    exp = st.expander("Edit budget amounts")
    exp.caption((f"{month_label(m)} has its own plan from your budget sheet; edits apply to this month only."
                 if own else "This month uses your standard plan; edits apply to every month that uses it."))
    df = pd.DataFrame([{
        "Section": r["section"], "Line": r["cat"], "Whose": WHO_NAME.get(r["owner"], "") if r["owner"] else "",
        "Budget": r["planned"], "Set aside": r["set_aside"] or None, "Spent": r["all"],
        "Zuha": r["zuha"], "Aneeq": r["aneeq"], "Shared": r["shared"], "Not assigned": r["none"],
        "Left": r["left"] if r["available"] or r["set_aside"] else None,
    } for r in rows])
    if df.empty:
        return
    mc = {c: st.column_config.NumberColumn(c, format="$%.0f", disabled=c != "Budget")
          for c in ["Budget", "Set aside", "Spent", "Zuha", "Aneeq", "Shared", "Not assigned", "Left"]}
    edited = exp.data_editor(df[["Section", "Line", "Whose", "Budget", "Set aside", "Spent"]], hide_index=True, width="stretch", key=f"bud-{m}",
                            column_config={**mc, "Section": st.column_config.TextColumn(disabled=True),
                                           "Line": st.column_config.TextColumn(disabled=True),
                                           "Whose": st.column_config.TextColumn(disabled=True)})
    if exp.button("Save budget changes", type="primary"):
        plan = fresh()[1].plan
        tgt = plan["byMonth"][m] if own else plan["budgets"]
        for _, r in edited.iterrows():
            v = float(r["Budget"] or 0)
            if v:
                tgt[r["Line"]] = v
            else:
                tgt.pop(r["Line"], None)
        save_config("plan", plan)
        st.success("Budget saved.")
        st.rerun()


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
        keep = {"Needs a person": not (who or ex or cb or pj), "All": True, "Big expenses": bool(pj and not cb),
                "Money between you": bool(cb), "Not counted": ex}[show]
        if not keep or (q and q not in f"{t['desc']} {c} {t.get('account','')}".lower()):
            continue
        line_val = proj_label.get(t.get("project")) if pj else ((t.get("for_line") or NO_LINE) if cb else c)
        recs.append({"Date": t["date"], "Merchant": t["desc"], "Paid from": PAID_NAME.get(L.payer_of(t) or "", "⚪ not set"),
                     "Amount": t["spend"], "Line": line_val,
                     "Who": (WHO_NAME.get(who, UNSET) if who else UNSET) if not (pj or cb or ex) else NO_ITEM,
                     "Item": t.get("proj_item") or NO_ITEM, "Status": status})
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
            "Status": st.column_config.TextColumn(disabled=True)})
    remember = st.checkbox("Remember these choices for the same merchant: apply to every month and to future statements",
                           value=True, key="remember")
    if st.button("Save changes", type="primary", key="save-tx"):
        changes: dict[str, dict] = {}
        learn: dict[str, dict] = {}
        byid = {t["id"]: t for t in L.txns}
        for i, (_, new) in enumerate(edited.iterrows()):
            old, t = df.iloc[i], byid[ids[i]]
            ch = {}
            cb = L.contrib_of(t)
            key = learn_key(t["desc"])
            if new["Line"] != old["Line"] and new["Line"] and new["Line"] != NO_LINE:
                if new["Line"] in label_proj:
                    ch["project"] = label_proj[new["Line"]]
                    if cb:
                        ch["for_line"] = None
                else:
                    ch["project"] = None
                    ch["proj_item"] = None
                    if cb:
                        ch["for_line"] = new["Line"]
                    elif remember:
                        learn.setdefault(key, {})["line"] = new["Line"]
                        ch["cat_override"] = None
                    else:
                        ch["cat_override"] = new["Line"]
            if new["Who"] != old["Who"] and not cb and new["Who"] != NO_ITEM:
                who = WHO_KEY.get(new["Who"] or "") if new["Who"] != UNSET else None
                if remember and who:
                    learn.setdefault(key, {})["who"] = who
                    ch["person"] = None
                else:
                    ch["person"] = who
            if (new["Item"] or NO_ITEM) != (old["Item"] or NO_ITEM):
                ch["proj_item"] = None if new["Item"] in (None, "", NO_ITEM) else new["Item"]
            if ch:
                changes[t["id"]] = ch
        if learn:
            rules = fresh()[1].rules
            rules.setdefault("learn", {})
            for k, v in learn.items():
                rules["learn"][k] = {**rules["learn"].get(k, {}), **v}
            save_config("rules", rules)
        if changes:
            update_txns(changes)
        if learn or changes:
            n = sum(1 for t in L.txns if learn_key(t["desc"]) in learn)
            st.session_state["flash"] = (f"Saved. Remembered {len(learn)} merchant{'s' if len(learn) != 1 else ''}, "
                                         f"applied to {n} charge{'s' if n != 1 else ''} across all months and to future statements."
                                         if learn else f"Saved {len(changes)} change{'s' if len(changes) != 1 else ''}.")
            st.rerun()
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))


def page_big(L: Ledger):
    html('<div class="lg-h2" style="margin-top:4px">Big expenses</div><p class="lg-note" style="margin:0 0 12px">One-off costs paid for by budget set aside '
         'from regular lines (usually Household Goods + Trips in Extras II). Tag a charge to one from Transactions by choosing ★ in the Line column.</p>')
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

            c1, c2 = st.columns(2)
            split_opts = {"By funding plan": "", "50:50": "even", "All Zuha": "zuha", "All Aneeq": "aneeq"}
            split = c1.selectbox(f"Settle-up split (funding plan = {stt['plan_pct']*100:.0f}% Zuha)", list(split_opts),
                                 index=list(split_opts.values()).index(p.get("split") or ""), key=f"split-{p['id']}")
            sec_names = [l for _, l in SECTIONS]
            cur = next((l for k, l in SECTIONS if k == (p.get("section") or DEFAULT_SECTION)), "Extras II")
            sec = c2.selectbox("Counts under", sec_names, index=sec_names.index(cur), key=f"sec-{p['id']}")
            if st.button("Save changes", key=f"save-{p['id']}", type="primary"):
                projects = fresh()[1].projects
                tgt = next(x for x in projects if x["id"] == p["id"])
                tgt["items"] = [{"name": str(r["Item"]), "est": float(r["Estimated"] or 0),
                                 **({"who": WHO_KEY[r["Whose"]]} if r.get("Whose") else {})}
                                for _, r in ed.iterrows() if str(r["Item"] or "").strip()]
                if split_opts[split]:
                    tgt["split"] = split_opts[split]
                else:
                    tgt.pop("split", None)
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


def page_settle(L: Ledger):
    html(ui.settle(L))


def page_statements(L: Ledger, d: dict, person: str):
    html('<div class="lg-h2" style="margin-top:4px">Statements</div>')
    api_key = secret("anthropic").get("api_key")
    model = secret("anthropic").get("model", "claude-sonnet-5-5")
    html('<p class="lg-note" style="margin:0 0 10px">Upload PDF statements from Chase, Wells Fargo or any other card. '
         'Claude reads each one; you check the totals and pick whose account it is, then add it to the ledger. '
         'The original PDF is saved to the shared Drive folder.</p>')
    files = st.file_uploader("Bank or card statement PDFs", type=["pdf"], accept_multiple_files=True, key="uploader")
    if files and st.button("Read statements", type="primary", disabled=not api_key):
        from ledger.parse import read_statement
        pend = st.session_state.setdefault("pending", {})
        for f in files:
            with st.spinner(f"Reading {f.name}… this usually takes under a minute"):
                try:
                    pdf = f.getvalue()
                    pend[f.name] = {"pdf": pdf, "res": read_statement(pdf, L, api_key, model), "name": f.name}
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
            cur = L.rules["payer"].get(res["account"])
            labels = list(PAYER_OPTS)
            idx = next((i for i, (k, v) in enumerate(PAYER_OPTS.items()) if v == cur), 0)
            payer = st.selectbox("Whose account is this?", labels, index=idx, key=f"payer-{name}")
            c1, c2 = st.columns([1, 4])
            if c1.button("Add to ledger", key=f"add-{name}", type="primary", disabled=not PAYER_OPTS[payer]):
                store = get_store()
                dd, LL = fresh()
                sid = uuid.uuid4().hex[:12]
                new, dup = LL.add_parsed(rows, sid, person)
                meta = store.add_statement({"id": sid, "filename": name, "account": res["account"],
                                            "period_start": res.get("start") or "", "period_end": res.get("end") or "",
                                            "uploaded_by": person, "uploaded_at": now_iso(), "n_added": len(new),
                                            "n_skipped": dup}, p["pdf"])
                store.save_txns(dd["txns"] + new)
                if LL.rules["payer"].get(res["account"]) != PAYER_OPTS[payer]:
                    LL.rules["payer"][res["account"]] = PAYER_OPTS[payer]
                    store.save_config("rules", LL.rules)
                st.session_state["pending"].pop(name, None)
                bump()
                st.success(f"Added {len(new)} transactions" + (f", skipped {dup} already here" if dup else "") + f" from {meta['filename']}.")
                st.rerun()
            if c2.button("Discard", key=f"drop-{name}"):
                st.session_state["pending"].pop(name, None)
                st.rerun()

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
    st.markdown("**Remembered merchants** (set from the Transactions page; these win over every other rule)")
    lrn = rules.get("learn") or {}
    lrdf = pd.DataFrame([{"Merchant": k, "Line": v.get("line", ""), "Who": WHO_NAME.get(v.get("who"), "")} for k, v in sorted(lrn.items())],
                        columns=["Merchant", "Line", "Who"])
    lred = st.data_editor(lrdf, hide_index=True, width="stretch", num_rows="dynamic", key="r-learn",
                          column_config={"Merchant": st.column_config.TextColumn(disabled=False),
                                         "Line": st.column_config.SelectboxColumn(options=[""] + L.all_categories()),
                                         "Who": st.column_config.SelectboxColumn(options=WHO_OPTS)})

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
        r["learn"] = {}
        for _, x in lred.iterrows():
            k = str(x["Merchant"] or "").strip().lower()
            if k and (x["Line"] or x["Who"]):
                r["learn"][k] = {**({"line": x["Line"]} if x["Line"] else {}), **({"who": WHO_KEY[x["Who"]]} if x["Who"] else {})}
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
        page_big(L)
    elif page == "Settle up":
        page_settle(L)
    elif not m:
        st.info("Add a statement on the Statements page to get started.")
    elif page == "Overview":
        page_overview(L, m)
    elif page == "Budget":
        page_budget(L, m)
    elif page == "Transactions":
        page_transactions(L, m, person)


main()
