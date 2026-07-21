#!/usr/bin/env python3
"""
FlowForge Dashboard Generator
Fetches all FlowForge-labelled tickets from Jira and regenerates
the dynamic sections of index.html in place.

Usage:
    python3 generate.py
    python3 generate.py --dry-run   # print diff, don't write

Requires:
    pip install requests python-dotenv
    JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN in environment or .env file
"""

import argparse
import html as html_lib
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ────────────────────────────────────────────────────────────────────

JIRA_URL   = os.environ.get("JIRA_URL",   "https://sisu-agile.atlassian.net")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
AI_COST_FIELD = "customfield_13682"

DASHBOARD_FILE = os.path.join(os.path.dirname(__file__), "index.html")

# Initiative → epic-group configuration.
# Each entry: (initiative_prod_key, [list of epic PROD keys that belong to it])
# Tickets are matched by their parent field pointing to one of these epic keys.
# A ticket whose parent is the initiative key itself (no sub-epic) goes into a
# catch-all group for that initiative.
# (slug, prod_key, iproj_label, display_title, {epic_key: display_title, ...})
# Epic titles are hardcoded here — never fetched from Jira — so the design never drifts.
INITIATIVES = [
    ("fox-uk",  "PROD-11100", "[15011]", "Fox UK (Day 1)", {
        "PROD-12307": "Fox UK — UAT Wave 1",
        "PROD-12353": "Fox UK — [FR-8] Save and Retrieve Quote",
        "PROD-13072": "Fox UK — [FR-13] Migration / Bugs &amp; Fixes",
        "PROD-13071": "Fox UK — Save Quotation Email",
        "PROD-12640": "Fox UK — [FR-14] Support of Affiliated Business Partners",
        "PROD-13070": "Fox UK — [FR-1] Q&amp;B flow / Fixes and bugs",
        "PROD-13820": "Fox — GO LIVE",
    }),
    ("travel",  "PROD-12933", "[15803]", "Fusion B2C US (Phase 1)", {
        "PROD-13143": "[FR-04] Requote 'Get a Quote' (Traveler's Details)",
        "PROD-13062": "[EHA Widget + MP] — Get Policy and Coverages details",
        "PROD-13400": "EHA Widget — Upload and Delete Case Documents",
        "PROD-13145": "Travel — Braintree Payment Integration",
        "PROD-13136": "Travel — Gadget Fields Integration",
        "PROD-13282": "Travel — [FR-09] Save &amp; Retrieve via Email",
        "PROD-13201": "CIL Library — USPG API Provider",
        "PROD-13245": "Fusion B2C US — Policy Recalculation for Contract Management (Amendments)",
    }),
    ("mddr",    "PROD-12356", "[15044]", "MDDR individual policies", {
        "PROD-12497": "MDDR — Individual Policies: E2E Testing",
        "PROD-13196": "MDDR — Individual Policies: Contract Modification &amp; Cancellation via eAPI",
        "PROD-13075": "MDDR — Expand Beneficiaries",
        "PROD-13221": "MDDR Open Policies — Beneficiary Creation Events (webhook intake)",
        "PROD-13223": "MDDR Open Policies — Beneficiary Modification Events (webhook intake)",
    }),
    ("nbg",     "PROD-13185", "[15045]", "NBG Motor", {
        "PROD-13244": "NBG Motor — API Modifications",
        "PROD-13170": "NBG Property — API Draft",
        "PROD-13171": "NBG Property — Quote/Offer Integration",
        "PROD-13312": "NBG Property — Documents Integration",
        "PROD-13320": "NBG Property — Apply for Policy Integration",
        "PROD-13267": "NBG UL — API Modifications",
        "PROD-13415": "NBG UL — Apply for Policy Integration",
        "PROD-13413": "NBG UL — Document Retrieval &amp; Upload Integration",
        "PROD-13535": "NBG Property — Amend &amp; Cancel Policy",
        "PROD-12920": "NBG Motor — Fix Missing Field Mappings",
        "PROD-13403": "NBG Health — Partner Flow &amp; Product Setup",
    }),
    ("nbg-standing-order", "PROD-13287", "[15045]", "NBG Financial Services (Payments, Commissions)", {
        "PROD-13576": "NBG Standing Order — API Modifications",
        "PROD-13577": "NBG Standing Order — Integration",
    }),
    ("clara",   "PROD-13092", "[15832]", "Clara EHA Beneficiary Management and MP Access", {
        "PROD-13255": "Clara EHA — CIL Beneficiary Management Implementation",
        "PROD-13225": "MDDR Open Policies — eAPI Integration: MDDR Device Fields",
        "PROD-12536": "Clara Replacement — Get Policy (Retail &amp; Meta Portal)",
        "PROD-13190": "Clara Replacement — Remove Unnecessary OnePay Fields",
        "PROD-12535": "Clara Replacement — Travel Sales Data Flows",
        "PROD-12730": "Clara Replacement — Post-sales Policy Amendments",
    }),
    ("global-ch",  "PROD-12331", "[18201]", "Global App CH Switzerland", {
        "PROD-12480": "CH — Person Details 2",
        "PROD-12481": "CH PI-III — Mailbox-List",
        "PROD-12482": "CH PI-III — Mailbox-Item",
        "PROD-12383": "CH — Person Details",
        "PROD-12800": "CH PI-II — Payment Frequency",
        "PROD-13301": "CH PI-III — Asynch Process Communication",
        "PROD-13307": "CH — Extend Product Type Enum",
        "PROD-12300": "CH — Motor Additional Data",
        "PROD-13686": "CH PI-III — Technical Debts",
        "PROD-13304": "CH PI-III — Customer Profile Delete",
        "PROD-12484": "CH PI-II — Motor Insurance Certificate",
    }),
    ("global-azd", "PROD-12339", "[18202]", "Global App AzD - Allianz Direct NL", {
        "PROD-12769": "AzD NL — Display All Policies",
        "PROD-12770": "AzD NL — Display Policy Details",
        "PROD-12773": "AzD NL — Display Claims",
        "PROD-13502": "Global App AzD NL — Risk Address &amp; Actions",
        "PROD-13500": "Global App AzD NL — Available Actions",
    }),
    ("global-azp", "PROD-12514", "[18204]", "Global App - AUS Az Partners", {
        "PROD-13082": "Allyz AUS — Get Emergency Numbers",
        "PROD-13083": "Allyz AUS — Hospital Finder",
        "PROD-13079": "AzP — Lounge Zone Access (QR code)",
    }),
    ("top-viaggi", "PROD-12344", "[15041]", "Travel Beneficiaries - Wave 1 - (ON/OFF Boarding) TOP VIAGGI (Italy)", {
        "PROD-12741": "Top Viaggi — [FR-1] Enable beneficiary creation",
    }),
    ("westpac",    "PROD-11253", "[15017]", "[Westpac] Post-sales data flows: Policy, Claim and credit card cancellations", {
        "PROD-12292": "Westpac — View Policy Details (Travel)",
        "PROD-13654": "Westpac — UAT Bugs",
    }),
    ("allyz-ca",   "PROD-13100", "[60999]", "Allyz Canada", {
        "PROD-13269": "Allyz CA — GetPolicy &amp; Setup",
    }),
    ("coverwise",  "PROD-12115", "[15005 · 15019]", "Coverwise - post go live", {
        "": "Partner Onboarding — New Integrations",
        "PROD-12116": "Coverwise — Production Issues",
    }),
    ("netrisk",    "PROD-12355", "[15043]", "Netrisk - COI Retrival", {
        "": "Netrisk — Grafana",
    }),
    ("bbva",       "PROD-13037", "[15036]", "[BBVA/SISU] Implementation of new business partner", {
        "": "BBVA — Grafana",
    }),
    ("globus-threat", "PROD-12332", "[18200]", "Global App - General work", {
        "PROD-13653": "Globus — Threat Model Remediation",
        "PROD-12978": "Global App — Login Beta+",
        "PROD-12923": "Global App — Virtual OE",
    }),
    ("ff-ba-pipeline", "PROD-13115", "[18200]", "AI Rollout", {
        "": "FlowForge — Tooling &amp; Infrastructure",
        "CIL-6148":   "[FlowForge] BA/PO Upstream Pipeline Epic",
        "PROD-13861": "FlowForge /flowforge.review — Replace Human Code Analysis Stage",
    }),
    ("bmw",        "PROD-13231", "[15037]", "BMW", {
        "PROD-13231": "BMW — Handle customer self-payment for service",
        "PROD-13233": "BMW — Handle empty ETA returned by RSA GET /geolocation",
    }),
    ("travel-claims",    "PROD-13491", "[Travel Claims]", "Travel Claims — Unified Claims View", {
        "PROD-13491": "Travel Claims — Single CIL Entry Point",
    }),
    ("clara-eha-widget", "PROD-12960", "[15832]", "Clara Emergency Home Assistance", {
        "PROD-12963": "EHA Widget — Create Case",
    }),
    ("jlr-wallbox",      "PROD-11449", "[15030]", "JLR Wallbox", {
        "PROD-11516": "JLR Wallbox — Internal E2E Testing",
    }),
    ("global-aal", "PROD-12340", "[18203]", "Global App Australia (AAL)", {
        "PROD-13791": "GlobaApp AAL OE — General Time Tracking",
        "PROD-13701": "AAL — PI 3 Planning",
    }),
    ("rrb",        "PROD-12919", "[15047]", "AU Regional Banks (RRB)", {
        "PROD-13809": "RRB — CIL Partner Integration",
    }),
    ("hood",       "PROD-12918", "[15048]", "Hood Group", {
        "PROD-13238": "Hood Group — FlowForge Integration",
        "": "Hood Group — General",
    }),
    ("cil-general","PROD-10026", "[15015]", "CIL General — Non-Billable", {
        "PROD-12925": "CIL API Versioning",
    }),
]

# Map every epic key → initiative slug (built at runtime)
EPIC_TO_INIT  = {}
INIT_EPICS    = {}  # slug → {epic_key: title}
INIT_PROD     = {}  # slug → prod key
INIT_IPROJ    = {}  # slug → iproj label
INIT_ITITLE   = {}  # slug → display title
for slug, prod_key, iproj, ititle, epics in INITIATIVES:
    INIT_PROD[slug]   = prod_key
    INIT_EPICS[slug]  = epics  # dict {key: title}
    INIT_IPROJ[slug]  = iproj
    INIT_ITITLE[slug] = ititle
    EPIC_TO_INIT[prod_key] = slug
    for e in epics:
        if e:  # skip empty-string placeholder keys
            EPIC_TO_INIT[e] = slug


# ── Jira helpers ──────────────────────────────────────────────────────────────

def jira_search(jql, fields, expand=None):
    auth = (JIRA_EMAIL, JIRA_TOKEN)
    fields_list = fields.split(",") if isinstance(fields, str) else fields
    all_issues, next_token = [], None
    expand_str = ",".join(expand) if isinstance(expand, list) else (expand or "")
    while True:
        url = f"{JIRA_URL}/rest/api/3/search/jql"
        if expand_str:
            url += f"?expand={expand_str}"
        body = {"jql": jql, "fields": fields_list, "maxResults": 100}
        if next_token:
            body["nextPageToken"] = next_token
        r = requests.post(url, auth=auth, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)
        if data.get("isLast", True) or not issues:
            break
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return all_issues


def _done_date_from_changelog(issue):
    """Return the date (YYYY-MM-DD) when this issue last transitioned to a Done
    status category, using the changelog embedded in the search response.
    Returns "" if no such transition is found."""
    changelog = issue.get("changelog", {})
    histories = changelog.get("histories", [])
    done_date = ""
    for history in histories:
        for item in history.get("items", []):
            if item.get("field") == "status":
                to_cat = item.get("toCategoryId", "") or ""
                to_str = (item.get("toString") or "").lower()
                # Jira Done category id is "3"; also match by name
                if to_cat == "3" or "done" in to_str:
                    ts = history.get("created", "")[:10]
                    if ts > done_date:
                        done_date = ts
    return done_date


def fetch_all_flowforge_tickets():
    """Return list of dicts with fields we care about."""
    # CIL board only — PROD-* tickets are excluded intentionally
    jql = 'project = CIL AND labels = "FlowForge" ORDER BY created ASC'
    fields = f"summary,status,assignee,reporter,parent,created,{AI_COST_FIELD},resolutiondate,labels"
    raw = jira_search(jql, fields, expand=["changelog"])
    tickets = []
    for issue in raw:
        f = issue["fields"]
        status      = f.get("status", {})
        stat_name   = status.get("name", "")
        stat_cat    = status.get("statusCategory", {}).get("name", "To Do")
        assignee    = (f.get("assignee") or {}).get("displayName", "Unassigned")
        reporter    = (f.get("reporter") or {}).get("displayName", "—")
        parent      = (f.get("parent") or {}).get("key", "")
        created_raw = f.get("created", "")[:10]
        ai_cost_raw = f.get(AI_COST_FIELD) or 0
        try:
            ai_cost = float(ai_cost_raw)
        except (TypeError, ValueError):
            ai_cost = 0.0
        # Use the changelog to find when the ticket actually moved to Done
        resolution = (f.get("resolutiondate") or "")[:10]
        if stat_cat == "Done":
            done_date = _done_date_from_changelog(issue) or resolution or created_raw
        else:
            done_date = ""
        tickets.append({
            "key":       issue["key"],
            "summary":   f.get("summary", ""),
            "status":    stat_name,
            "cat":       stat_cat,
            "assignee":  assignee,
            "reporter":  reporter,
            "parent":    parent,
            "created":   created_raw,
            "ai_cost":   ai_cost,
            "done_date": done_date,
        })
    return tickets


# ── Badge helpers ─────────────────────────────────────────────────────────────

def badge_class(status, cat):
    if cat == "Done":
        return "badge-done"
    if cat == "In Progress":
        if status in ("In Code Review", "Review"):
            return "badge-review"
        return "badge-wip"
    # To Do
    if "AI-Generation" in status:
        return "badge-ai"
    if status == "Paused / On hold":
        return "badge-hold"
    return "badge-todo"


def badge_html(status, cat):
    bc = badge_class(status, cat)
    display = status if cat != "To Do" or status not in ("To Do",) else "To Do"
    return f'<span class="badge {bc}">{html_lib.escape(display)}</span>'


# ── Section builders ──────────────────────────────────────────────────────────

def build_ticket_row(t):
    key     = t["key"]
    summary = html_lib.escape(t["summary"])
    assignee = html_lib.escape(t["assignee"])
    reporter = html_lib.escape(t["reporter"])
    created  = t["created"]
    cost_str = f'${t["ai_cost"]:.2f}' if t["ai_cost"] > 0 else "—"
    cost_cls = "t-cost" if t["ai_cost"] > 0 else "t-cost-na"
    done_str = t["done_date"] if t["done_date"] else "—"
    done_cls = "t-done" if t["done_date"] else "t-done-na"
    badge    = badge_html(t["status"], t["cat"])
    return (
        f'<tr>'
        f'<td class="t-key"><a href="{JIRA_URL}/browse/{key}" target="_blank">{key}</a></td>'
        f'<td class="t-summary">{summary}</td>'
        f'<td class="t-who">{assignee}</td>'
        f'<td class="t-who">{reporter}</td>'
        f'<td>{badge}</td>'
        f'<td class="t-date">{created}</td>'
        f'<td class="{cost_cls}">{cost_str}</td>'
        f'<td class="{done_cls}">{done_str}</td>'
        f'</tr>'
    )


def build_epic_group(epic_key, epic_title, tickets):
    # Render even with 0 tickets — baseline always shows the group
    rows = "\n            ".join(build_ticket_row(t) for t in tickets) if tickets else "            "
    count = len(tickets)
    eg_key_html = (
        f'<a href="{JIRA_URL}/browse/{epic_key}" target="_blank">{epic_key}</a>'
        if epic_key else ""
    )
    count_str = f'{count} ticket{"s" if count != 1 else ""}' if count > 0 else ""
    count_span = f'\n          <span class="eg-count">{count_str}</span>' if count_str else ""
    return (
        f'\n            <div class="epic-group">\n'
        f'        <div class="epic-group-head">\n'
        f'          <span class="eg-key">{eg_key_html}</span>\n'
        f'          <span class="eg-title">{epic_title}</span>{count_span}\n'
        f'        </div>\n'
        f'        <table class="ticket-table">\n'
        f'          <thead><tr><th>Key</th><th>Summary</th><th>Assignee</th>'
        f'<th>Author</th><th>Status</th><th>Created</th><th>AI Cost</th><th>Done</th></tr></thead>\n'
        f'          <tbody>\n'
        f'            {rows}\n'
        f'          </tbody>\n'
        f'        </table>\n'
        f'      </div>\n'
    )


def build_initiative_body(slug, tickets_by_epic):
    """Build the initiative-body div content for one initiative."""
    epics = INIT_EPICS[slug]   # dict {epic_key: display_title}
    prod_key = INIT_PROD[slug]
    parts = []

    # Render all configured epic groups in order (even empty — baseline shows them).
    # An empty-string key "" in the config means: no eg-key displayed, tickets come
    # from the initiative's prod_key directly.
    seen_epics = set(k for k in epics.keys() if k)
    seen_epics.add(prod_key)
    for epic_key, title in epics.items():
        if epic_key == "":
            # Direct-tickets group: prod_key-parented tickets with no eg-key shown
            ts = tickets_by_epic.get(prod_key, [])
        else:
            ts = tickets_by_epic.get(epic_key, [])
        parts.append(build_epic_group(epic_key, title, ts))

    # Tickets parented directly to the initiative PROD key, but only if no explicit
    # "" placeholder was configured for them already
    if "" not in epics and prod_key not in epics:
        direct = tickets_by_epic.get(prod_key, [])
        if direct:
            parts.append(build_epic_group("", f"{slug.replace('-',' ').title()} — General", direct))

    # Any tickets with unexpected parent keys (show them under their parent)
    for epic_key, ts in tickets_by_epic.items():
        if epic_key not in seen_epics:
            title = epics.get(epic_key, epic_key)
            parts.append(build_epic_group(epic_key, title, ts))

    body = "".join(parts)
    return f'    <div class="initiative-body">\n{body}\n    </div>\n'


def build_icounts(tickets):
    done   = sum(1 for t in tickets if t["cat"] == "Done")
    wip    = sum(1 for t in tickets if t["cat"] == "In Progress")
    ai_gen = sum(1 for t in tickets if "AI-Generation" in t["status"])
    todo   = sum(1 for t in tickets if t["cat"] == "To Do" and "AI-Generation" not in t["status"])
    total_cost = sum(t["ai_cost"] for t in tickets if t["ai_cost"] > 0)
    parts = []
    if wip:    parts.append(f'<span class="badge badge-wip">{wip} active</span>')
    if done:   parts.append(f'<span class="badge badge-done">{done} done</span>')
    if todo:   parts.append(f'<span class="badge badge-todo">{todo} to do</span>')
    if ai_gen: parts.append(f'<span class="badge badge-ai">{ai_gen} AI-gen</span>')
    if total_cost > 0:
        parts.append(f'<span class="badge-cost">✦ ${total_cost:.0f}</span>')
    return "\n        ".join(parts)


# ── Author section ─────────────────────────────────────────────────────────────

def build_author_ticket(t):
    key     = t["key"]
    summary = html_lib.escape(t["summary"])
    badge   = badge_html(t["status"], t["cat"])
    return (
        f'        <div class="author-ticket">'
        f'<a class="at-key" href="{JIRA_URL}/browse/{key}" target="_blank">{key}</a>'
        f'<span class="at-title">{summary}</span>'
        f'{badge}</div>\n'
    )


def build_author_section(all_tickets):
    # Group by reporter (author)
    by_author = defaultdict(list)
    for t in all_tickets:
        by_author[t["reporter"]].append(t)

    # Sort authors by ticket count desc
    authors = sorted(by_author.items(), key=lambda x: -len(x[1]))

    cards = []
    for name, tickets in authors:
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        initials = ''.join(w[0].upper() for w in name.split()[:2]) or "??"
        count = len(tickets)
        rows  = "".join(build_author_ticket(t) for t in sorted(tickets, key=lambda t: t["key"]))
        cards.append(
            f'    <div class="author-card" data-author="{slug}">\n'
            f'      <div class="author-head">\n'
            f'        <div class="author-avatar">{initials}</div>\n'
            f'        <div class="author-name">{html_lib.escape(name)}</div>\n'
            f'        <div class="author-count">{count} ticket{"s" if count != 1 else ""}</div>\n'
            f'      </div>\n'
            f'      <div class="author-body">\n'
            f'{rows}'
            f'      </div>\n'
            f'    </div>\n\n'
        )
    return '<div class="author-grid">\n\n' + "".join(cards) + '</div>\n'


# ── Leaderboard builders ──────────────────────────────────────────────────────

def lb_card(rank, initials, name, count, count_lbl, tickets_html, open_=False, green=False):
    rank_cls  = "rank-1" if rank == 1 else ("rank-2" if rank == 2 else "rank-3")
    avatar_cls = "lb-avatar green-grad" if green else "lb-avatar"
    count_cls  = "lb-count green-count" if green else "lb-count"
    open_cls   = " open" if open_ else ""
    return (
        f'\n    <div class="lb-card{open_cls}">'
        f'\n      <div class="lb-head" onclick="this.closest(\'.lb-card\').classList.toggle(\'open\')">'
        f'\n        <span class="lb-rank {rank_cls}">{rank}</span>'
        f'\n        <div class="{avatar_cls}">{initials}</div>'
        f'\n        <span class="lb-name">{html_lib.escape(name)}</span>'
        f'\n        <span class="{count_cls}">{count}</span><span class="lb-count-lbl">{count_lbl}</span>'
        f'\n        <span class="lb-arrow">▶</span>'
        f'\n      </div>'
        f'\n      <div class="lb-body">{tickets_html}'
        f'\n      </div>'
        f'\n    </div>\n'
    )


def compute_ranks(sorted_items, key_fn):
    ranks, prev_val, prev_rank, cur = [], None, 0, 0
    for item in sorted_items:
        cur += 1
        val = key_fn(item)
        if val != prev_val:
            prev_rank = cur
        ranks.append(prev_rank)
        prev_val = val
    return ranks


def _month_buckets(tickets, date_key):
    """Group tickets into calendar-month buckets using the given date field.
    Tickets with no date for that field are skipped.
    Returns list of (year, month, [tickets]) sorted newest-first."""
    by_month = defaultdict(list)
    for t in tickets:
        d = t.get(date_key, "")
        if d and len(d) >= 7:
            ym = d[:7]   # "YYYY-MM"
            by_month[ym].append(t)
    return sorted(by_month.items(), reverse=True)   # newest month first


def _month_label(ym):
    """'2026-06' → 'June 2026'"""
    y, m = ym.split("-")
    month_names = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    return f"{month_names[int(m)]} {y}"


def _leaderboard_month_block(ym, tickets, top_n, group_key, count_lbl,
                              row_badge_fn, border_color, open_first, green):
    """Build one initiative-block accordion for a single month's leaderboard."""
    by_person = defaultdict(list)
    for t in tickets:
        by_person[t[group_key]].append(t)
    if group_key == "assignee":
        by_person.pop("Unassigned", None)

    ranked = sorted(by_person.items(), key=lambda x: (-len(x[1]), x[0]))
    top    = ranked[:top_n]
    if not top:
        return ""
    ranks  = compute_ranks(top, lambda x: -len(x[1]))

    total_people  = len(ranked)
    total_tickets = sum(len(v) for _, v in ranked)
    person_lbl    = "developers" if group_key == "assignee" else "authors"

    cards = ""
    for i, ((name, person_tickets), rank) in enumerate(zip(top, ranks)):
        initials = ''.join(w[0].upper() for w in name.split()[:2]) or "??"
        rows = "".join(
            f'\n        <div class="lb-ticket">'
            f'<a class="lt-key" href="{JIRA_URL}/browse/{t["key"]}" target="_blank">{t["key"]}</a>'
            f'<span class="lt-title">{html_lib.escape(t["summary"])}</span>'
            f'{row_badge_fn(t)}</div>'
            for t in sorted(person_tickets, key=lambda t: t["key"])
        )
        cards += lb_card(rank, initials, name, len(person_tickets), count_lbl,
                         rows, open_=(i == 0 and open_first), green=green)

    badge_cls = "badge-done" if green else "badge-wip"
    ticket_cls = "badge-done" if green else "badge-todo"
    label = _month_label(ym)
    is_current = (ym == date.today().strftime("%Y-%m"))
    label_suffix = " (so far)" if is_current else ""

    return (
        f'  <div class="initiative-block" style="margin-bottom:16px">\n'
        f'    <div class="initiative-head" onclick="this.closest(\'.initiative-block\').classList.toggle(\'open\')" style="border-left:3px solid {border_color}">\n'
        f'      <span class="iarrow">▶</span>\n'
        f'      <span class="ititle">{label}{label_suffix}</span>\n'
        f'      <div class="icounts">'
        f'<span class="badge {badge_cls}">{total_people} {person_lbl}</span>'
        f'<span class="badge {ticket_cls}">{total_tickets} {count_lbl}</span></div>\n'
        f'    </div>\n'
        f'    <div class="initiative-body">\n'
        f'      <div class="leaderboard" style="padding:12px 0">\n'
        f'{cards}'
        f'      </div>\n'
        f'    </div>\n'
        f'  </div>\n\n'
    )




# ── Epic title lookup ─────────────────────────────────────────────────────────

def fetch_epic_titles(epic_keys):
    """Fetch display titles for a list of epic keys from Jira."""
    titles = {}
    auth = (JIRA_EMAIL, JIRA_TOKEN)
    for key in epic_keys:
        if not key:
            continue
        try:
            r = requests.get(
                f"{JIRA_URL}/rest/api/3/issue/{key}",
                auth=auth, params={"fields": "summary"}, timeout=15
            )
            if r.ok:
                titles[key] = r.json().get("fields", {}).get("summary", key)
        except Exception:
            titles[key] = key
    return titles


# ── Template filler ───────────────────────────────────────────────────────────
# The generator ONLY fills named <!-- SLOT:name --> placeholders.
# It NEVER modifies CSS, class names, wrappers, or any structural HTML.
# All layout lives in template.html permanently. generate.py touches data only.

TEMPLATE_FILE  = os.path.join(os.path.dirname(__file__), "template.html")
SLOT_RE        = re.compile(r'<!-- SLOT:(\w+) -->')


def _slot(name, content):
    return f'<!-- SLOT:{name} -->', content


def fill_template(all_tickets):
    """Read template.html, fill every SLOT with computed data, return index.html content."""

    with open(TEMPLATE_FILE) as f:
        html = f.read()

    # Verify all expected slots are present — abort rather than produce broken output
    expected = {'last_pull','badge_stats','summary_dynamic','avg_ai_cost_card',
                'initiatives','leaderboard_created','leaderboard_done',
                'leaderboard_top10_done','by_author'}
    found = set(SLOT_RE.findall(html))
    missing = expected - found
    if missing:
        sys.exit(f"ERROR: template.html is missing slots: {missing}. "
                 f"Do not edit template.html slots manually.")

    # ── Route tickets to initiatives ──────────────────────────────────────────
    init_ticket_map = defaultdict(lambda: defaultdict(list))
    unrouted = []
    for t in all_tickets:
        parent = t["parent"]
        slug   = EPIC_TO_INIT.get(parent)
        if slug:
            init_ticket_map[slug][parent].append(t)
        else:
            unrouted.append(t)
    if unrouted:
        print(f"  ⚠ {len(unrouted)} tickets not routed to any initiative:", file=sys.stderr)
        for t in unrouted[:10]:
            print(f"    {t['key']} parent={t['parent']}", file=sys.stderr)

    # ── Build initiatives slot ────────────────────────────────────────────────
    init_blocks = []
    active_init_count = 0
    for slug, prod_key, iproj, ititle, _ in INITIATIVES:
        tickets_by_epic  = init_ticket_map.get(slug, {})
        all_init_tickets = [t for ts in tickets_by_epic.values() for t in ts]
        if not all_init_tickets:
            continue
        active_init_count += 1
        icounts_html = build_icounts(all_init_tickets)
        head = (
            f'    <div class="initiative-block" data-init="{slug}">\n'
            f'    <div class="initiative-head" onclick="toggleInit(this)">\n'
            f'      <span class="iarrow">▶</span>\n'
            f'      <span class="ikey"><a href="{JIRA_URL}/browse/{prod_key}" target="_blank" style="color:inherit;text-decoration:none">{prod_key}</a></span>\n'
            f'      <span class="iproj">{html_lib.escape(iproj)}</span>\n'
            f'      <span class="ititle">{html_lib.escape(ititle)}</span>\n'
            f'      <div class="icounts">\n        {icounts_html}\n      </div>\n'
            f'    </div>\n'
        )
        body = build_initiative_body(slug, tickets_by_epic)
        init_blocks.append(head + body + '  </div>\n\n')

    # ── Build summary bar dynamic cards ──────────────────────────────────────
    total   = len(all_tickets)
    done    = sum(1 for t in all_tickets if t["cat"] == "Done")
    wip     = sum(1 for t in all_tickets if t["cat"] == "In Progress")
    todo    = sum(1 for t in all_tickets if t["cat"] == "To Do")
    authors = len(set(t["reporter"] for t in all_tickets))
    costs   = [t["ai_cost"] for t in all_tickets if t["ai_cost"] > 0]
    avg_cost_str = f'${sum(costs)/len(costs):.2f}' if costs else "—"
    cost_lbl     = f'Avg AI Cost / Ticket ({len(costs)} tickets)'

    summary_dynamic = (
        f'    <div class="summary-card purple"><div class="num">{total}</div><div class="lbl">Total Tickets</div></div>\n'
        f'    <div class="summary-card green"><div class="num">{done}</div><div class="lbl">Done</div></div>\n'
        f'    <div class="summary-card amber"><div class="num">{wip}</div><div class="lbl">In Progress / Review</div></div>\n'
        f'    <div class="summary-card gray"><div class="num">{todo}</div><div class="lbl">To Do</div></div>\n'
        f'    <div class="summary-card blue"><div class="num">{active_init_count}</div><div class="lbl">Initiatives</div></div>\n'
        f'    <div class="summary-card red"><div class="num">{authors}</div><div class="lbl">Authors</div></div>'
    )
    avg_ai_cost_card = (
        f'<div class="summary-card amber"><div class="num">{avg_cost_str}</div>'
        f'<div class="lbl">{cost_lbl}</div></div>'
    )

    # ── Build leaderboard slots ───────────────────────────────────────────────
    created_blocks = _leaderboard_slot_content(all_tickets, "created", 5, "reporter",
                                                "tickets", lambda t: badge_html(t["status"], t["cat"]),
                                                "#d97706", green=False)
    done_blocks    = _leaderboard_slot_content(
                        [t for t in all_tickets if t["cat"] == "Done"],
                        "done_date", 5, "reporter",
                        "done", lambda t: badge_html(t["status"], t["cat"]),
                        "#16a34a", green=True)
    top10_blocks   = _leaderboard_slot_content(
                        [t for t in all_tickets if t["cat"] == "Done"],
                        "done_date", 10, "assignee",
                        "done", lambda t: '<span class="badge badge-done">Done</span>',
                        "#16a34a", green=True)

    today_str = date.today().strftime("%d %b %Y")

    # ── Fill all slots ────────────────────────────────────────────────────────
    replacements = {
        'last_pull':             today_str,
        'badge_stats':           f'✦ FlowForge · {total} tickets · {active_init_count} initiatives · {authors} authors',
        'summary_dynamic':       summary_dynamic,
        'avg_ai_cost_card':      avg_ai_cost_card,
        'initiatives':           ''.join(init_blocks),
        'leaderboard_created':   created_blocks,
        'leaderboard_done':      done_blocks,
        'leaderboard_top10_done': top10_blocks,
        'by_author':             build_author_section(all_tickets),
    }

    def replace_slot(m):
        name = m.group(1)
        if name not in replacements:
            sys.exit(f"ERROR: unknown slot '{name}' in template.html")
        return replacements[name]

    return SLOT_RE.sub(replace_slot, html)


def _leaderboard_slot_content(tickets, date_key, top_n, group_key,
                               count_lbl, row_badge_fn, border_color, green):
    """Build all monthly accordion blocks for a leaderboard slot."""
    buckets = _month_buckets(tickets, date_key)
    blocks = ""
    for i, (ym, month_tickets) in enumerate(buckets):
        blocks += _leaderboard_month_block(
            ym, month_tickets, top_n=top_n, group_key=group_key,
            count_lbl=count_lbl, row_badge_fn=row_badge_fn,
            border_color=border_color, open_first=(i == 0), green=green
        )
    return blocks


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Regenerate FlowForge dashboard from Jira")
    parser.add_argument("--dry-run", action="store_true", help="Print stats only, don't write file")
    args = parser.parse_args()

    if not JIRA_EMAIL or not JIRA_TOKEN:
        sys.exit("Set JIRA_EMAIL and JIRA_API_TOKEN environment variables (or use a .env file)")

    print("Fetching FlowForge tickets from Jira…")
    tickets = fetch_all_flowforge_tickets()
    tickets = [t for t in tickets if t["status"] != "Closed"]
    print(f"  {len(tickets)} tickets (Closed excluded)")

    if args.dry_run:
        by_cat = defaultdict(int)
        for t in tickets:
            by_cat[t["cat"]] += 1
        print(f"  Done: {by_cat['Done']}  In Progress: {by_cat['In Progress']}  To Do: {by_cat['To Do']}")
        costs = [t["ai_cost"] for t in tickets if t["ai_cost"] > 0]
        if costs:
            print(f"  Avg AI cost: ${sum(costs)/len(costs):.2f} ({len(costs)} tickets with cost)")
        return

    print("Filling template…")
    new_html = fill_template(tickets)

    with open(DASHBOARD_FILE, "w") as f:
        f.write(new_html)
    print(f"  Written {DASHBOARD_FILE}")

    print(f"  {len(new_html):,} chars written")


if __name__ == "__main__":
    main()
