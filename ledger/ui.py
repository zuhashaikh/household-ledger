"""Look and feel: the ledger page's palette, type and components, rendered as HTML inside Streamlit."""
from __future__ import annotations

from html import escape

from .logic import DEFAULT_SECTION, PAYER_LABEL, PEOPLE, SECTIONS, Ledger, month_label

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=Public+Sans:wght@400;500;600;700&display=swap');
:root{
  --bg:#F3F5F2; --surface:#FFFFFF; --sunk:#E8ECE7; --line:#D5DBD3;
  --ink:#1C2320; --muted:#5D6862; --accent:#1F5E57;
  --zuha:#7B3FA0; --aneeq:#2560A8; --shared:#C4901A; --none:#9AA39E;
  --good:#2E7D4F; --warn:#B26A00; --bad:#B23A2E;
  --display:"Bricolage Grotesque",ui-sans-serif,system-ui,sans-serif;
  --body:"Public Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
}
html,body,[class*="css"],.stApp,.stMarkdown,button,input,select,textarea{font-family:var(--body)!important}
.stApp{background:var(--bg)}
[data-testid="stHeader"]{background:transparent}
.block-container{padding-top:2.2rem!important;max-width:1120px}
h1,h2,h3{font-family:var(--display)!important;letter-spacing:-.01em;color:var(--ink)}
[data-testid="stSidebar"]{background:var(--surface);border-right:1px solid var(--line)}
.lg-eyebrow{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600}
.lg-title{font-family:var(--display);font-size:30px;font-weight:700;color:var(--ink);margin:0 0 14px;line-height:1.15}
.lg-h2{font-family:var(--display);font-size:19px;font-weight:700;color:var(--ink);margin:22px 0 8px}
.lg-muted{color:var(--muted)}
.lg-note{color:var(--muted);font-size:13px;margin:8px 0 0;max-width:72ch}
.num{font-variant-numeric:tabular-nums}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:1px}
.d-zuha{background:var(--zuha)}.d-aneeq{background:var(--aneeq)}.d-shared{background:var(--shared)}.d-none,.d-unset{background:var(--none)}

.lg-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:6px 0 4px}
.lg-summary>div{background:var(--surface);padding:16px 18px;display:flex;flex-direction:column;gap:4px;min-width:0}
.lg-summary .big{font-family:var(--display);font-size:28px;font-weight:700;color:var(--ink);line-height:1.1}
@media (max-width:640px){.lg-summary{grid-template-columns:1fr}}

.lg-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
.lg-table{border-collapse:collapse;width:100%;font-size:14px;color:var(--ink);margin:0!important;border:0!important}
.lg-table th,.lg-table td{border-left:0!important;border-right:0!important;border-top:0!important}
.lg-scroll{margin-bottom:2px}
.lg-table th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600;text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap;background:var(--surface)}
.lg-table td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:middle}
.lg-table tr:last-child td{border-bottom:0}
.lg-table .r{text-align:right}
.lg-table tr.grp td{background:var(--sunk);padding:7px 12px}
.lg-table tr.sub td{font-size:13px;padding-top:5px;padding-bottom:5px;color:var(--muted)}
.lg-table tr.sub td:first-child{padding-left:28px}
.lg-table tr.tot td{font-weight:700;border-top:1px solid var(--line)}
.lg-table .why{display:block;font-size:11px;color:var(--muted);margin-top:2px}
.lg-table .aside{display:block;font-size:11px;color:var(--shared);margin-top:2px;white-space:nowrap}

.bar{position:relative;height:10px;background:var(--sunk);border-radius:99px;min-width:110px;overflow:hidden}
.bar span{position:absolute;top:0;bottom:0}
.s-zuha{background:var(--zuha)}.s-aneeq{background:var(--aneeq)}.s-shared{background:var(--shared)}.s-none{background:var(--none)}
.bar.over{outline:1.5px solid var(--bad);outline-offset:1px}
.pill{font-size:12px;font-weight:600;padding:2px 9px;border-radius:99px;white-space:nowrap;border:1px solid currentColor;display:inline-block}
.pill.ok{color:var(--good)}.pill.near{color:var(--warn)}.pill.over{color:var(--bad)}.pill.nobud{color:var(--muted)}

.lg-card{border:1px solid var(--line);border-radius:12px;background:var(--surface);padding:18px;margin:0 0 6px}
.lg-card h3{font-size:21px;margin:0 0 12px;padding:0!important}
.lg-stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:14px}
.lg-stats .v{font-family:var(--display);font-size:22px;font-weight:700;color:var(--ink)}
.lg-cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
@media (max-width:820px){.lg-cols{grid-template-columns:1fr}}
.lg-legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--muted);margin:2px 0 8px}

/* Streamlit widgets, nudged toward the same look */
.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button{border-radius:8px;font-weight:600}
.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"]{background:var(--accent);border-color:var(--accent)}
[data-testid="stDataFrame"],[data-testid="stDataEditor"]{border:1px solid var(--line);border-radius:12px;overflow:hidden}
[data-testid="stExpander"] details{border-radius:12px;border-color:var(--line);background:var(--surface)}
div[data-testid="stSegmentedControl"] button{font-weight:600}
</style>
"""


def m(x: float, cents: bool = False) -> str:
    s = f"${abs(x):,.2f}" if cents else f"${abs(x):,.0f}"
    return ("−" if x < -0.004 else "") + s


def e(s) -> str:
    return escape(str(s if s is not None else ""))


def header(person: str, title: str = "Zuha & Aneeq Ledger") -> str:
    return (f'<div class="lg-eyebrow">Household spending · signed in as {e(PEOPLE.get(person, person))}</div>'
            f'<div class="lg-title">{e(title)}</div>'
            '<div class="lg-legend" style="margin:-6px 0 12px"><span><span class="dot d-zuha"></span>Zuha</span>'
            '<span><span class="dot d-aneeq"></span>Aneeq</span><span><span class="dot d-shared"></span>Shared</span></div>')


def summary(L: Ledger, mo: str) -> str:
    res = L.compute(mo)
    owed, change = L.owed_through(mo)
    pay = {"zuha": 0.0, "aneeq": 0.0}
    for t in L.deduction_txns(mo) if L.month_txns(mo, with_deductions=False) else []:
        pay[t["payer"]] = pay.get(t["payer"], 0) + t["spend"]

    def cell(who, name, bank):
        total = res["paid"][who]
        sub = f'{bank} {m(total - pay[who])} · {m(pay[who])} taken from pay' if pay[who] else f'From {bank}'
        return (f'<div><span class="lg-eyebrow"><span class="dot d-{who}"></span>Spent by {name}</span>'
                f'<span class="big num">{m(total)}</span><span class="lg-muted num" style="font-size:13px">{sub}</span></div>')
    return ('<div class="lg-summary">' + cell("zuha", "Zuha", "Chase") + cell("aneeq", "Aneeq", "Wells Fargo")
            + (f'<div><span class="lg-eyebrow">Aneeq owes Zuha</span><span class="big num" style="color:var(--zuha)">{m(owed if owed >= 1 else 0)}</span>'
               if owed > -1 else
               f'<div><span class="lg-eyebrow">Aneeq&#39;s credit</span><span class="big num" style="color:var(--aneeq)">{m(-owed)}</span>')
            + f'<span class="lg-muted num" style="font-size:13px">{"counts toward his next dues · " if owed <= -1 else ""}through {e(month_label(mo).split()[0])}'
            + (f' · {"+" if change > 0 else "−"}{m(abs(change))} this month' if abs(change) >= 1 else "") + '</span></div>'
            '</div>')


def _state(spent: float, budget: float | None) -> str:
    if budget is None:
        return ""
    if not budget:
        return '<span class="pill over">no budget</span>' if spent >= .5 else ""
    if spent > budget + .5:
        return f'<span class="pill over">{m(spent - budget)} over</span>'
    if spent > budget * .85:
        return f'<span class="pill near">{m(budget - spent)} left</span>'
    return f'<span class="pill ok">{m(budget - spent)} left</span>'


def sections(L: Ledger, mo: str) -> str:
    sm = L.section_matrix(mo)
    rows = sm["rows"]
    zero = dict(zuha=0.0, aneeq=0.0, shared=0.0, unset=0.0)
    cols = ["zuha", "aneeq"] + [k for k in ("shared", "unset") if any(abs(r.get(k, 0)) >= .5 for r in rows.values())]
    out = []

    def line(label, r, budget=None, cls=""):
        r = r or zero
        tot = sum(r.get(k, 0) for k in cols)
        cells = "".join(f'<td class="r num" style="color:var(--{"muted" if k == "unset" else k})">{m(r.get(k, 0)) if abs(r.get(k, 0)) >= .5 else "–"}</td>' for k in cols)
        bud = "" if budget is None else (m(budget) if budget else "–")
        name = e(label) if cls else f"<b>{e(label)}</b>"
        out.append(f'<tr class="{cls}"><td>{name}</td>{cells}<td class="r num"><b>{m(tot)}</b></td><td class="r num">{bud}</td><td>{_state(tot, budget)}</td></tr>')

    for k, label in SECTIONS:
        reg, big = rows.get(k, zero), rows.get("big:" + k)
        both = {c: reg.get(c, 0) + (big or {}).get(c, 0) for c in zero}
        line(label, both, sm["budget"].get(k, 0))
        if big:
            line("regular spending", reg, cls="sub")
            for p in L.projects:
                if (p.get("section") or DEFAULT_SECTION) == k and rows.get("proj:" + p["id"]):
                    line(p["name"], rows["proj:" + p["id"]], cls="sub")
    if rows.get("other"):
        line("Not in the budget", rows["other"])
    allr = {c: sum(r.get(c, 0) for key, r in rows.items() if not key.startswith("proj:")) for c in zero}
    tot = sum(allr[c] for c in cols)
    btot = sum(sm["budget"].get(k, 0) for k, _ in SECTIONS)
    out.append(f'<tr class="tot"><td>Total</td>{"".join(f"<td class=r>{m(allr[c])}</td>" for c in cols)}<td class="r num">{m(tot)}</td><td class="r num">{m(btot) if btot else "–"}</td><td></td></tr>')
    head = "".join(f'<th class="r">{e(PAYER_LABEL[k])}</th>' for k in cols)
    note = ('Big expenses count under Extras II in the month they&#39;re charged. Extras II works as a running fund: '
            'what isn&#39;t spent carries forward, and leftover Core and Extras I money is added once a month is closed.')
    return (f'<div class="lg-h2">By section and account, {e(month_label(mo))}</div>'
            f'<div class="lg-scroll"><table class="lg-table"><thead><tr><th>Section</th>{head}<th class="r">Total</th><th class="r">Budget</th><th></th></tr></thead>'
            f'<tbody>{"".join(out)}</tbody></table></div><p class="lg-note">{note}</p>')


def budget(L: Ledger, mo: str) -> str:
    rows = L.budget_rows(mo)
    out, last = [], None
    by_group: dict[str, list] = {}
    for r in rows:
        by_group.setdefault(r["section"], []).append(r)
    for r in rows:
        g = r["section"]
        if g != last:
            last = g
            gs = sum(x["all"] for x in by_group[g])
            gb = sum(x["available"] for x in by_group[g])
            label = dict(SECTIONS).get(g, g)
            out.append(f'<tr class="grp"><td colspan="8"><span class="lg-eyebrow">{e(label)}</span> <span class="lg-muted num" style="font-size:13px;margin-left:8px">{m(gs)} spent{(" of " + m(gb)) if gb else ""}</span></td></tr>')
        b = r["available"]
        scale = max(b, r["all"], 1)
        x, segs = 0.0, ""
        for k in ("zuha", "aneeq", "shared", "none"):
            w = max(0.0, r[k]) / scale * 100
            segs += f'<span class="s-{k}" style="left:{x:.2f}%;width:{w:.2f}%"></span>'
            x += w
        if b and r["all"] > b:
            segs += f'<span style="left:{b/scale*100:.2f}%;width:2px;background:var(--ink)"></span>'
        owner = r["owner"]
        own = f'<span class="why"><span class="dot d-{owner}"></span>{"Split 50:50" if owner == "shared" else PEOPLE[owner] + "&#39;s"}</span>' if owner else ""
        aside = f'<span class="aside">−{m(r["set_aside"])} for {e(r["set_aside_for"].rsplit(" ", 1)[0])}</span>' if r["set_aside"] else ""
        if not b and r["set_aside"] and not r["all"]:
            st = '<span class="pill nobud">All set aside</span>'
        elif not b and not r["set_aside"]:
            st = '<span class="pill nobud">No budget</span>' if r["all"] < .5 else '<span class="pill over">no budget</span>'
        else:
            st = _state(r["all"], b)
        cell = lambda k: f'<td class="r num" style="color:var(--{k})">{m(r[k]) if abs(r[k]) >= .5 else "–"}</td>'
        out.append(f'<tr><td><b>{e(r["cat"])}</b>{own}</td><td class="r num">{m(r["planned"]) if r["planned"] else "–"}{aside}</td>'
                   f'<td class="r num">{m(r["all"])}</td><td style="width:24%"><div class="bar {"over" if b and r["all"] > b else ""}">{segs}</div></td>'
                   f'{cell("zuha")}{cell("aneeq")}{cell("shared")}<td>{st}</td></tr>')
    legend = ('<div class="lg-legend"><span><span class="dot d-zuha"></span>Zuha</span><span><span class="dot d-aneeq"></span>Aneeq</span>'
              '<span><span class="dot d-shared"></span>Shared</span><span><span class="dot d-none"></span>Not assigned</span></div>')
    return (f'<div class="lg-h2">Budget vs. spent by line, {e(month_label(mo))}</div>{legend}'
            '<div class="lg-scroll"><table class="lg-table"><thead><tr><th>Line</th><th class="r">Budget</th><th class="r">Spent</th><th>Split</th>'
            '<th class="r">Zuha</th><th class="r">Aneeq</th><th class="r">Shared</th><th>Status</th></tr></thead>'
            f'<tbody>{"".join(out) or "<tr><td colspan=8 class=lg-muted>No budget or spending this month.</td></tr>"}</tbody></table></div>')


def big_card(L: Ledger, p: dict) -> str:
    s = L.proj_stats(p)
    names = {"zuha": "Zuha", "aneeq": "Aneeq", "shared": "50:50"}
    item_rows = []
    for i in p.get("items") or []:
        who = (f'<span class="dot d-{i["who"]}"></span>{names[i["who"]]}' if i.get("who") else '<span class="lg-muted">project split</span>')
        est = m(float(i.get("est") or 0)) if i.get("est") else "–"
        sp = s["by_item"].get(i["name"], 0)
        item_rows.append(f'<tr><td>{e(i["name"])}</td><td>{who}</td><td class="r num">{est}</td><td class="r num">{m(sp, True) if sp else "–"}</td></tr>')
    items = "".join(item_rows)
    if abs(s["unmatched"]) >= .5:
        items += f'<tr class="sub"><td>Not matched to an item</td><td></td><td></td><td class="r num">{m(s["unmatched"], True)}</td></tr>'
    z = s["z_pct"]
    split_txt = "50:50" if abs(z - .5) < 1e-9 else ("All Zuha" if z >= .999 else "All Aneeq" if z <= .001 else f"{z*100:.0f}% Zuha / {100 - z*100:.0f}% Aneeq")
    owners = sorted({i["who"] for i in p.get("items") or [] if i.get("who")})
    fhead = f'Split {split_txt} · paid from the Extras II fund' + (" · some items belong to one person" if owners else "")
    charges = "".join(f'<tr><td class="num lg-muted" style="white-space:nowrap">{e(t["date"])}</td><td><b>{e(t["desc"])}</b><span class="why">{e(t.get("account",""))} · {e(PAYER_LABEL.get(L.payer_of(t) or "unset"))}{(" · " + e(t["proj_item"])) if t.get("proj_item") else ""}</span></td><td class="r num">{m(t["spend"], True)}</td></tr>' for t in s["txns"])
    charges_html = (f'<div class="lg-eyebrow" style="margin:14px 0 6px">Charges</div><div class="lg-scroll"><table class="lg-table"><tbody>{charges}</tbody></table></div>'
                    if charges else f'<p class="lg-note">No charges yet. In Transactions, choose “★ {e(p["name"])}” as a charge&#39;s line.</p>')
    return (f'<div class="lg-card"><h3>{e(p["name"])}</h3>'
            f'<div class="lg-stats"><div><span class="lg-eyebrow">Estimated</span><div class="v num">{m(s["est"])}</div></div>'
            f'<div><span class="lg-eyebrow">Spent so far (in statements)</span><div class="v num">{m(s["spent"])}</div><span class="lg-muted" style="font-size:13px">{len(s["txns"])} transaction{"s" if len(s["txns"]) != 1 else ""}</span></div></div>'
            '<div class="lg-cols">'
            f'<div><div class="lg-eyebrow" style="margin-bottom:6px">Items</div><div class="lg-scroll"><table class="lg-table"><thead><tr><th>Item</th><th>Whose</th><th class="r">Estimated</th><th class="r">Spent so far</th></tr></thead><tbody>{items or "<tr><td colspan=4 class=lg-muted>No items yet.</td></tr>"}</tbody></table></div></div>'
            f'<div><div class="lg-eyebrow" style="margin-bottom:6px">How it&#39;s paid for</div><p class="lg-note" style="margin:0">{fhead}. '
            'Each charge comes out of the shared fund; in the settle-up each of you covers your share, and whoever pays more is credited.</p></div>'
            f'</div>{charges_html}</div>')


def settle(L: Ledger, mo: str | None = None) -> str:
    rows = L.settle_rows()
    if not rows:
        return '<p class="lg-note">Add a statement to see what&#39;s owed.</p>'
    run = rows[-1]["running"]
    if run >= 1:
        verdict, col = f"Aneeq owes Zuha {m(run)}", "zuha"
    elif run <= -1:
        verdict, col = f"Aneeq has {m(-run)} credit toward his next dues", "aneeq"
    else:
        verdict, col = "All settled", "good"
    bal = lambda x: (f'<b style="color:var(--zuha)">owes {m(x)}</b>' if x >= 1 else
                     f'<b style="color:var(--aneeq)">credit {m(-x)}</b>' if x <= -1 else '<b class="lg-muted">settled</b>')
    body_rows = []
    for r in reversed(rows):
        skipped = f'<span class="why">{m(r["skipped"])} not assigned</span>' if r["skipped"] >= 1 else ""
        you = ("+" + m(r["you_sent"])) if r["you_sent"] >= .5 else "–"
        he = ("−" + m(r["he_sent"])) if r["he_sent"] >= .5 else "–"
        absorbed = f'<span class="lg-muted">{m(r["absorbed"])}</span>' if r["absorbed"] >= 1 else "–"
        body_rows.append(f'<tr><td><b>{e(month_label(r["month"]))}</b>{skipped}</td><td class="r num">{bal(r["start"])}</td>'
                         f'<td class="r num">{m(r["gross"])}</td><td class="r num">{you}</td><td class="r num">{absorbed}</td>'
                         f'<td class="r num"><b>{m(r["due"])}</b></td><td class="r num">{he}</td><td class="r num">{bal(r["running"])}</td></tr>')
    body = "".join(body_rows)
    return ('<div class="lg-summary" style="grid-template-columns:1fr"><div><span class="lg-eyebrow">Settle-up</span>'
            f'<span class="big num" style="color:var(--{col})">{verdict}</span></div></div>'
            '<p class="lg-note"><b>Due each month</b>: Aneeq&#39;s lines, his half of shared lines and his share of big expenses that Zuha paid, '
            'plus money Zuha sent him. If he paid for more of Zuha&#39;s share than she did of his, that extra is absorbed against Core and Extras I '
            'that month (Zuha never owes him). <b>Money he sends</b> pays, in order: anything owed from earlier months, Core, Extras I, '
            'Extras II and big expenses, then money Zuha sent him. Anything left over is credit toward his next month&#39;s dues.</p>'
            '<div class="lg-scroll" style="margin-top:12px"><table class="lg-table"><thead><tr><th>Month</th><th class="r">Start of month</th>'
            '<th class="r">His share Zuha paid</th><th class="r">Zuha sent him</th><th class="r">His extra, absorbed</th><th class="r">Due this month</th>'
            '<th class="r">He sent</th><th class="r">End of month</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>' + settle_breakdown(L, rows, mo))


def settle_breakdown(L: Ledger, rows: list, mo: str | None) -> str:
    r = next((x for x in rows if x["month"] == mo), rows[-1] if rows else None)
    if not r:
        return ""
    trs = []
    for a in r["alloc"]:
        if a["due"] < .005:
            continue
        unpaid = (f'<b style="color:var(--zuha)">{m(a["unpaid"], True)}</b>' if a["unpaid"] >= .005 else '<span class="good-t">paid</span>')
        trs.append(f'<tr><td><b>{e(a["label"])}</b></td><td class="r num">{m(a["due"], True)}</td>'
                   f'<td class="r num">{m(a["covered_by_spending"], True) if a["covered_by_spending"] >= .005 else "–"}</td>'
                   f'<td class="r num">{m(a["paid"], True) if a["paid"] >= .005 else "–"}</td><td class="r num">{unpaid}</td></tr>')
    if r["running"] <= -1:
        end = f'<b style="color:var(--aneeq)">{m(-r["running"], True)} left over → credit toward next month</b>'
    elif r["running"] >= 1:
        end = f'<b style="color:var(--zuha)">{m(r["running"], True)} still owed at the end of the month</b>'
    else:
        end = '<b class="good-t">All paid</b>'
    sent = f'He sent {m(r["he_sent"], True)}' + (f' and had {m(-r["start"], True)} credit from earlier' if r["start"] <= -1 else "")
    ab = f' {m(r["absorbed"], True)} of his own extra spending was absorbed.' if r["absorbed"] >= 1 else ""
    return (f'<div class="lg-h2">Where Aneeq&#39;s money went, {e(month_label(r["month"]))}</div>'
            f'<p class="lg-note" style="margin:0 0 8px">{sent}. It pays, in order: anything owed from earlier months, Core, Extras I, '
            f'Extras II and big expenses, other, then money Zuha sent him. Whatever is left is credit for next month.{ab}</p>'
            '<div class="lg-scroll"><table class="lg-table"><thead><tr><th>In order</th><th class="r">He owed</th>'
            '<th class="r">Covered by his own spending</th><th class="r">Paid from money he sent</th><th class="r">Still owed</th></tr></thead>'
            f'<tbody>{"".join(trs) or "<tr><td colspan=5 class=lg-muted>Nothing owed this month.</td></tr>"}'
            f'<tr class="tot"><td colspan="5">{end}</td></tr></tbody></table></div>')


def person_budget(L: Ledger, mo: str, who: str) -> str:
    """Budget check for one person: their lines + half of shared lines vs the spending that counts toward them."""
    pb = L.person_budget(mo, who)
    name = PEOPLE[who]
    left = pb["left"]
    col = "good" if left >= 0 else "bad"
    head = (f'<div class="lg-summary"><div><span class="lg-eyebrow"><span class="dot d-{who}"></span>{name}&#39;s budget</span>'
            f'<span class="big num">{m(pb["budget"])}</span><span class="lg-muted" style="font-size:13px">own lines + half of shared</span></div>'
            f'<div><span class="lg-eyebrow">Spent on {name}&#39;s lines</span><span class="big num">{m(pb["spent"])}</span>'
            f'<span class="lg-muted" style="font-size:13px">whoever paid; big expenses not included</span></div>'
            f'<div><span class="lg-eyebrow">{"Left" if left >= 0 else "Over"}</span><span class="big num" style="color:var(--{col})">{m(abs(left))}</span></div></div>')
    order = {k: i for i, (k, _) in enumerate(SECTIONS)}
    rows = sorted(pb["rows"], key=lambda r: (order.get(r["section"], 9), -r["budget"], r["line"].lower()))
    out, last = [], None
    for r in rows:
        if r["section"] != last:
            last = r["section"]
            out.append(f'<tr class="grp"><td colspan="5"><span class="lg-eyebrow">{e(dict(SECTIONS).get(last, last))}</span></td></tr>')
        b, sp = r["budget"], r["spent"]
        scale = max(b, sp, 1)
        bar = (f'<div class="bar {"over" if sp > b + .5 else ""}"><span class="s-{who}" style="left:0;width:{max(0, sp) / scale * 100:.1f}%"></span>'
               + (f'<span style="left:{b / scale * 100:.1f}%;width:2px;background:var(--ink)"></span>' if b and sp > b else "") + '</div>')
        tag = "half" if r["share"] == .5 else ("own" if r["share"] == 1 else "")
        out.append(f'<tr><td><b>{e(r["line"])}</b><span class="why">'
                   f'{"Shared line, " + name + "&#39;s half" if tag == "half" else ("Not on the budget" if not r["on_plan"] else name + "&#39;s line")}</span></td>'
                   f'<td class="r num">{m(b) if b else "–"}</td><td class="r num">{m(sp, True) if abs(sp) >= .5 else "–"}</td>'
                   f'<td style="width:28%">{bar}</td><td>{_state(sp, b) if (b or abs(sp) >= .5) else ""}</td></tr>')
    note = ""
    if who == "aneeq" and pb["paid_by_them"] < .5:
        note = ('<p class="lg-note" style="color:var(--warn)">Aneeq&#39;s accounts aren&#39;t in the ledger yet, so this only shows what was '
                'paid from Zuha&#39;s accounts on his lines. It fills in once his Wells Fargo is synced or uploaded.</p>')
    note += ('<p class="lg-note">Core and Extras I only. Extras II is a shared fund: see the Extras II fund on the Overview and Big expenses tabs.</p>')
    if pb["unassigned"] >= 1:
        note += (f'<p class="lg-note">{m(pb["unassigned"])} of spending this month has no person yet and isn&#39;t counted for anyone. '
                 'Assign it on the Not in budget or Transactions tab.</p>')
    return (f'{head}{note}<div class="lg-scroll" style="margin-top:10px"><table class="lg-table"><thead><tr><th>Line</th><th class="r">{e(name)}&#39;s budget</th>'
            f'<th class="r">Spent</th><th></th><th>Status</th></tr></thead><tbody>{"".join(out)}</tbody></table></div>')


def fund_panel(L: Ledger, mo: str | None = None, compact: bool = False) -> str:
    F = L.fund()
    rows = F["rows"]
    if not rows:
        return ""
    cur = next((r for r in rows if r["month"] == mo), rows[-1])
    bal = cur["balance"]
    col = "good" if bal >= 0 else "bad"
    outlook = ""
    if F["low"] < 0:
        when = f'about {F["months_to_zero"]} month{"s" if F["months_to_zero"] != 1 else ""} to refill' if F["months_to_zero"] else "won&#39;t refill at the current pace"
        outlook = (f'<span class="big num" style="color:var(--bad)">{m(F["low"])}</span><span class="lg-muted" style="font-size:13px">'
                   f'low point after planned big expenses · {when}</span>')
    else:
        outlook = (f'<span class="big num" style="color:var(--good)">{m(F["low"])}</span><span class="lg-muted" style="font-size:13px">'
                   'after planned big expenses</span>')
    head = ('<div class="lg-summary">'
            f'<div><span class="lg-eyebrow">Extras II fund, end of {e(month_label(cur["month"]).split()[0])}</span>'
            f'<span class="big num" style="color:var(--{col})">{m(bal)}</span><span class="lg-muted" style="font-size:13px">'
            f'{"saved up" if bal >= 0 else "spent ahead of future months"}</span></div>'
            f'<div><span class="lg-eyebrow">{e(month_label(cur["month"]).split()[0])}: in / out</span>'
            f'<span class="big num">+{m(cur["x2"] + cur["leftover"] + cur["topups"])} <span class="lg-muted" style="font-size:20px">/</span> −{m(cur["regular"] + cur["big"])}</span>'
            f'<span class="lg-muted" style="font-size:13px">{"leftover from Core &amp; Extras I counted" if cur["closed"] else "Core &amp; Extras I leftover counts once the month is closed"}</span></div>'
            f'<div><span class="lg-eyebrow">Outlook</span>{outlook}</div></div>')
    if compact:
        return head
    trs = []
    for r in reversed(rows):
        lo = (m(r["leftover"]) if r["closed"] else f'<span class="lg-muted" title="Counts once the month is closed">{m(max(0, r["leftover_raw"]))} pending</span>') if r["leftover_raw"] > .5 or r["closed"] else "–"
        big = ", ".join(f'{e(k)} {m(v)}' for k, v in r["by_proj"].items()) or "–"
        trs.append(f'<tr><td><b>{e(month_label(r["month"]))}</b></td><td class="r num">+{m(r["x2"])}</td><td class="r num">{lo}</td>'
                   f'<td class="r num">{("+" + m(r["topups"])) if r["topups"] else "–"}</td><td class="r num">−{m(r["regular"])}</td>'
                   f'<td style="font-size:13px">{big}</td><td class="r num"><b style="color:var(--{"good" if r["balance"] >= 0 else "bad"})">{m(r["balance"])}</b></td></tr>')
    plan = " · ".join(f'{e(k)} {m(v)}' for k, v in F["planned"].items())
    proj = (f'<p class="lg-note">Outlook: the standard Extras II budget is {m(F["std"])}/month and recurring Extras II spending has averaged '
            f'{m(F["everyday"])}, so about {m(F["per_month"])}/month is left for big expenses. Still planned (estimate less spent so far): {plan or "nothing"}'
            + (f'; undated top-ups {m(F["undated_topups"])}' if F["undated_topups"] else "") + '. Leftover from Core and Extras I comes on top of this.</p>')
    pending = [r for r in F["pending"]]
    warn = ('<p class="lg-note" style="color:var(--warn)">Close a month (below the table) once both of you have all its statements in. '
            'Until then its Core and Extras I leftover isn&#39;t counted, because missing statements (e.g. Aneeq&#39;s rent) would make it look far bigger than it is.</p>'
            if pending else "")
    return (head + proj + warn +
            '<div class="lg-scroll" style="margin-top:10px"><table class="lg-table"><thead><tr><th>Month</th><th class="r">Extras II budget</th>'
            '<th class="r">Core &amp; Extras I leftover</th><th class="r">Top-ups</th><th class="r">Everyday Extras II</th><th>Big expenses</th><th class="r">Fund balance</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></div>')
