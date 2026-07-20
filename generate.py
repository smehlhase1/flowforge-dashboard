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
# (slug, prod_key, iproj_label, display_title, [epic_keys])
INITIATIVES = [
    ("fox-uk",             "PROD-11100", "[15011]",           "Fox UK (Day 1)",                                                          ["PROD-12307","PROD-12353","PROD-13072","PROD-13071","PROD-12640","PROD-13070","PROD-13820"]),
    ("travel",             "PROD-12933", "[15803]",           "Fusion B2C US (Phase 1)",                                                 ["PROD-13143","PROD-13062","PROD-13400","PROD-13145","PROD-13136","PROD-13282","PROD-13201","PROD-13245"]),
    ("mddr",               "PROD-12356", "[15044]",           "MDDR individual policies",                                                ["PROD-12497","PROD-13196","PROD-13075","PROD-13221","PROD-13223"]),
    ("nbg",                "PROD-13185", "[15045]",           "NBG Motor",                                                               ["PROD-13244","PROD-13170","PROD-13171","PROD-13312","PROD-13320","PROD-13267","PROD-13415","PROD-13413","PROD-13535","PROD-12920","PROD-13403"]),
    ("nbg-standing-order", "PROD-13287", "[15045]",           "NBG Financial Services (Payments, Commissions)",                         ["PROD-13576","PROD-13577"]),
    ("clara",              "PROD-13092", "[15832]",           "Clara EHA Beneficiary Management and MP Access",                         ["PROD-13255","PROD-13225","PROD-12536","PROD-13190","PROD-12535","PROD-12730"]),
    ("global-ch",          "PROD-12331", "[18201]",           "Global App CH Switzerland",                                               ["PROD-12480","PROD-12481","PROD-12482","PROD-12383","PROD-12800","PROD-13301","PROD-13307","PROD-12300","PROD-13686","PROD-13304","PROD-12484"]),
    ("global-azd",         "PROD-12339", "[18202]",           "Global App AzD - Allianz Direct NL",                                     ["PROD-12769","PROD-12770","PROD-12773","PROD-13502","PROD-13500"]),
    ("global-azp",         "PROD-12514", "[18204]",           "Global App - AUS Az Partners",                                           ["PROD-13082","PROD-13083","PROD-13079"]),
    ("top-viaggi",         "PROD-12344", "[15041]",           "Travel Beneficiaries - Wave 1 - (ON/OFF Boarding) TOP VIAGGI (Italy)",   ["PROD-12741"]),
    ("westpac",            "PROD-11253", "[15017]",           "[Westpac] Post-sales data flows: Policy, Claim and credit card cancellations", ["PROD-12292","PROD-13654"]),
    ("allyz-ca",           "PROD-13100", "[60999]",           "Allyz Canada",                                                            ["PROD-13269"]),
    ("coverwise",          "PROD-12115", "[15005 · 15019]",   "Coverwise - post go live",                                               ["PROD-12116"]),
    ("netrisk",            "PROD-12355", "[15043]",           "Netrisk - COI Retrival",                                                  []),
    ("bbva",               "PROD-13037", "[15036]",           "[BBVA/SISU] Implementation of new business partner",                      []),
    ("globus-threat",      "PROD-12332", "[18200]",           "Global App - General work",                                               ["PROD-13653","PROD-12978","PROD-12923"]),
    ("ff-ba-pipeline",     "PROD-13115", "[18200]",           "AI Rollout",                                                              ["PROD-13861","CIL-6148"]),
    ("bmw",                "PROD-13231", "[15037]",           "BMW",                                                                     ["PROD-13231","PROD-13233"]),
    ("travel-claims",      "PROD-13491", "[Travel Claims]",   "Travel Claims — Unified Claims View",                                    ["PROD-13491"]),
    ("clara-eha-widget",   "PROD-12960", "[15832]",           "Clara Emergency Home Assistance",                                        ["PROD-12963"]),
    ("jlr-wallbox",        "PROD-11449", "[15030]",           "JLR Wallbox",                                                             ["PROD-11516"]),
    ("global-aal",         "PROD-12340", "[18203]",           "Global App Australia (AAL)",                                              ["PROD-13791","PROD-13701"]),
    ("rrb",                "PROD-12919", "[15047]",           "AU Regional Banks (RRB)",                                                 ["PROD-13809"]),
    ("hood",               "PROD-12918", "[15048]",           "Hood Group",                                                              ["PROD-13238"]),
    ("cil-general",        "PROD-10026", "[15015]",           "CIL General — Non-Billable",                                             ["PROD-12925"]),
]

# Map every epic key → initiative slug (built at runtime)
EPIC_TO_INIT = {}
INIT_EPICS   = {}  # slug → [epic keys]
INIT_PROD    = {}  # slug → prod key
INIT_IPROJ   = {}  # slug → iproj label
INIT_ITITLE  = {}  # slug → display title
for slug, prod_key, iproj, ititle, epics in INITIATIVES:
    INIT_PROD[slug]   = prod_key
    INIT_EPICS[slug]  = epics
    INIT_IPROJ[slug]  = iproj
    INIT_ITITLE[slug] = ititle
    EPIC_TO_INIT[prod_key] = slug
    for e in epics:
        EPIC_TO_INIT[e] = slug


# ── Jira helpers ──────────────────────────────────────────────────────────────

def jira_search(jql, fields, max_results=500):
    auth = (JIRA_EMAIL, JIRA_TOKEN)
    url  = f"{JIRA_URL}/rest/api/3/search/jql"
    fields_list = fields.split(",") if isinstance(fields, str) else fields
    all_issues, next_token = [], None
    while True:
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


def fetch_all_flowforge_tickets():
    """Return list of dicts with fields we care about."""
    # CIL board only — PROD-* tickets are excluded intentionally
    jql = 'project = CIL AND labels = "FlowForge" ORDER BY created ASC'
    fields = f"summary,status,assignee,reporter,parent,created,{AI_COST_FIELD},resolutiondate,labels"
    raw = jira_search(jql, fields)
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
        done_date   = (f.get("resolutiondate") or "")[:10]
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
    if not tickets:
        return ""
    rows = "\n              ".join(build_ticket_row(t) for t in tickets)
    count = len(tickets)
    eg_key_html = (
        f'<a href="{JIRA_URL}/browse/{epic_key}" target="_blank" '
        f'style="color:inherit;text-decoration:none">{epic_key}</a>'
        if epic_key else ""
    )
    return (
        f'      <div class="epic-group">\n'
        f'          <div class="epic-group-head">\n'
        f'            <span class="eg-key">{eg_key_html}</span>\n'
        f'            <span class="eg-title">{html_lib.escape(epic_title)}</span>\n'
        f'            <span class="eg-count">{count} ticket{"s" if count != 1 else ""}</span>\n'
        f'          </div>\n'
        f'          <table class="ticket-table">\n'
        f'            <thead><tr><th>Key</th><th>Summary</th><th>Assignee</th>'
        f'<th>Author</th><th>Status</th><th>Created</th><th>AI Cost</th><th>Done</th></tr></thead>\n'
        f'            <tbody>\n'
        f'              {rows}\n'
        f'            </tbody>\n'
        f'          </table>\n'
        f'      </div>\n'
    )


def build_initiative_body(slug, tickets_by_epic, epic_titles):
    """Build the initiative-body div content for one initiative."""
    epics = INIT_EPICS[slug]
    prod_key = INIT_PROD[slug]
    parts = []

    # Known epics in order
    seen_epics = set()
    for epic_key in epics:
        ts = tickets_by_epic.get(epic_key, [])
        title = epic_titles.get(epic_key, epic_key)
        if ts:
            parts.append(build_epic_group(epic_key, title, ts))
            seen_epics.add(epic_key)

    # Tickets parented directly to the initiative PROD key
    direct = tickets_by_epic.get(prod_key, [])
    if direct:
        parts.append(build_epic_group("", f"{slug.replace('-',' ').title()} — General", direct))
        seen_epics.add(prod_key)

    # Any tickets with unexpected parent keys (show them under their parent)
    for epic_key, ts in tickets_by_epic.items():
        if epic_key not in seen_epics:
            title = epic_titles.get(epic_key, epic_key)
            parts.append(build_epic_group(epic_key, title, ts))

    body = "".join(parts)
    return f'    <div class="initiative-body">\n{body}    </div>\n'


def build_icounts(tickets):
    done = sum(1 for t in tickets if t["cat"] == "Done")
    wip  = sum(1 for t in tickets if t["cat"] == "In Progress")
    todo = sum(1 for t in tickets if t["cat"] == "To Do")
    parts = []
    if done: parts.append(f'<span class="badge badge-done">{done} done</span>')
    if wip:  parts.append(f'<span class="badge badge-wip">{wip} active</span>')
    if todo: parts.append(f'<span class="badge badge-todo">{todo} to do</span>')
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
    return "".join(cards)


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


def build_created_leaderboard(all_tickets):
    by_author = defaultdict(list)
    for t in all_tickets:
        by_author[t["reporter"]].append(t)
    ranked = sorted(by_author.items(), key=lambda x: -len(x[1]))
    top5   = ranked[:5]
    ranks  = compute_ranks(top5, lambda x: -len(x[1]))
    total_authors  = len(ranked)
    total_tickets  = sum(len(v) for _, v in ranked)
    today = date.today().strftime("%b %d, %Y")

    cards = ""
    for i, ((name, tickets), rank) in enumerate(zip(top5, ranks)):
        initials = ''.join(w[0].upper() for w in name.split()[:2]) or "??"
        rows = "".join(
            f'\n        <div class="lb-ticket">'
            f'<a class="lt-key" href="{JIRA_URL}/browse/{t["key"]}" target="_blank">{t["key"]}</a>'
            f'<span class="lt-title">{html_lib.escape(t["summary"])}</span>'
            f'{badge_html(t["status"], t["cat"])}</div>'
            for t in sorted(tickets, key=lambda t: t["key"])
        )
        cards += lb_card(rank, initials, name, len(tickets), "tickets", rows, open_=(i == 0))

    return (
        f'<h2>🏆 Top 5 Authors — Most FlowForge Tickets Created</h2>\n\n'
        f'  <div class="initiative-block" style="margin-bottom:16px">\n'
        f'    <div class="initiative-head" onclick="this.closest(\'.initiative-block\').classList.toggle(\'open\')" style="border-left:3px solid #d97706">\n'
        f'      <span class="iarrow">▶</span>\n'
        f'      <span class="ititle">Jun 18 – {today}</span>\n'
        f'      <div class="icounts"><span class="badge badge-wip">{total_authors} authors</span>'
        f'<span class="badge badge-todo">{total_tickets} tickets</span></div>\n'
        f'    </div>\n'
        f'    <div class="initiative-body">\n'
        f'      <div class="leaderboard" style="padding:12px 0">\n'
        f'{cards}'
        f'      </div>\n'
        f'    </div>\n'
        f'  </div>\n\n  '
    )


def build_done_leaderboard(all_tickets):
    done_tickets = [t for t in all_tickets if t["cat"] == "Done"]
    by_author = defaultdict(list)
    for t in done_tickets:
        by_author[t["reporter"]].append(t)
    ranked = sorted(by_author.items(), key=lambda x: (-len(x[1]), x[0]))
    top5   = ranked[:5]
    ranks  = compute_ranks(top5, lambda x: -len(x[1]))
    total_authors = len(ranked)
    total_done    = sum(len(v) for _, v in ranked)
    today = date.today().strftime("%b %d, %Y")

    cards = ""
    for i, ((name, tickets), rank) in enumerate(zip(top5, ranks)):
        initials = ''.join(w[0].upper() for w in name.split()[:2]) or "??"
        rows = "".join(
            f'\n        <div class="lb-ticket">'
            f'<a class="lt-key" href="{JIRA_URL}/browse/{t["key"]}" target="_blank">{t["key"]}</a>'
            f'<span class="lt-title">{html_lib.escape(t["summary"])}</span>'
            f'{badge_html(t["status"], t["cat"])}</div>'
            for t in sorted(tickets, key=lambda t: t["key"])
        )
        cards += lb_card(rank, initials, name, len(tickets), "done", rows, open_=(i == 0), green=True)

    return (
        f'<h2>✅ Top 5 Authors — Most FlowForge Tickets Done</h2>\n\n'
        f'  <div class="initiative-block" style="margin-bottom:16px">\n'
        f'    <div class="initiative-head" onclick="this.closest(\'.initiative-block\').classList.toggle(\'open\')" style="border-left:3px solid #16a34a">\n'
        f'      <span class="iarrow">▶</span>\n'
        f'      <span class="ititle">Jun 18 – {today}</span>\n'
        f'      <div class="icounts"><span class="badge badge-done">{total_authors} authors</span>'
        f'<span class="badge badge-done">{total_done} tickets done</span></div>\n'
        f'    </div>\n'
        f'    <div class="initiative-body">\n'
        f'      <div class="leaderboard" style="padding:12px 0">\n'
        f'{cards}'
        f'      </div>\n'
        f'    </div>\n'
        f'  </div>\n\n  '
    )


def build_top10_devs(all_tickets):
    done_tickets = [t for t in all_tickets if t["cat"] == "Done"]
    by_dev = defaultdict(list)
    for t in done_tickets:
        by_dev[t["assignee"]].append(t)
    by_dev.pop("Unassigned", None)
    ranked = sorted(by_dev.items(), key=lambda x: (-len(x[1]), x[0]))
    top10  = ranked[:10]
    ranks  = compute_ranks(top10, lambda x: -len(x[1]))
    total_devs = len(ranked)
    total_done = sum(len(v) for _, v in ranked)
    today = date.today().strftime("%b %d, %Y")

    cards = ""
    for i, ((name, tickets), rank) in enumerate(zip(top10, ranks)):
        initials = ''.join(w[0].upper() for w in name.split()[:2]) or "??"
        rows = "".join(
            f'\n        <div class="lb-ticket">'
            f'<a class="lt-key" href="{JIRA_URL}/browse/{t["key"]}" target="_blank">{t["key"]}</a>'
            f'<span class="lt-title">{html_lib.escape(t["summary"])}</span>'
            f'<span class="badge badge-done">Done</span></div>'
            for t in sorted(tickets, key=lambda t: t["key"])
        )
        cards += lb_card(rank, initials, name, len(tickets), "done", rows, open_=(i == 0), green=True)

    return (
        f'<h2>🏅 Top 10 Developers — Most FlowForge Tickets Done</h2>\n\n'
        f'  <div class="initiative-block" style="margin-bottom:16px">\n'
        f'    <div class="initiative-head" onclick="this.closest(\'.initiative-block\').classList.toggle(\'open\')" style="border-left:3px solid #16a34a">\n'
        f'      <span class="iarrow">▶</span>\n'
        f'      <span class="ititle">Jun 18 – {today}</span>\n'
        f'      <div class="icounts"><span class="badge badge-done">{total_devs} developers</span>'
        f'<span class="badge badge-done">{total_done} tickets done</span></div>\n'
        f'    </div>\n'
        f'    <div class="initiative-body">\n'
        f'      <div class="leaderboard" style="padding:12px 0">\n'
        f'{cards}'
        f'      </div>\n'
        f'    </div>\n'
        f'  </div>\n\n'
        f'  <!-- ══ Section 6: Top 10 Assignees — Active Work ══ -->\n  '
    )


def build_summary_bar(all_tickets, static_cards_html):
    total = len(all_tickets)
    done  = sum(1 for t in all_tickets if t["cat"] == "Done")
    wip   = sum(1 for t in all_tickets if t["cat"] == "In Progress")
    todo  = sum(1 for t in all_tickets if t["cat"] == "To Do")

    # Authors (unique reporters)
    authors = len(set(t["reporter"] for t in all_tickets))

    # Avg AI cost (sum of non-zero / count of non-zero)
    costs = [t["ai_cost"] for t in all_tickets if t["ai_cost"] > 0]
    avg_cost_str = f'${sum(costs)/len(costs):.2f}' if costs else "—"
    cost_lbl = f'Avg AI Cost / Ticket ({len(costs)} tickets)'

    dynamic = (
        f'    <div class="summary-card purple"><div class="num">{total}</div><div class="lbl">Total Tickets</div></div>\n'
        f'    <div class="summary-card green"><div class="num">{done}</div><div class="lbl">Done</div></div>\n'
        f'    <div class="summary-card amber"><div class="num">{wip}</div><div class="lbl">In Progress / Review</div></div>\n'
        f'    <div class="summary-card gray"><div class="num">{todo}</div><div class="lbl">To Do</div></div>\n'
        f'    <div class="summary-card blue"><div class="num">{len(INITIATIVES)}</div><div class="lbl">Initiatives</div></div>\n'
        f'    <div class="summary-card red"><div class="num">{authors}</div><div class="lbl">Authors</div></div>\n'
    )

    # Replace Avg AI Cost card in the static block
    updated_static = re.sub(
        r'<div class="summary-card amber"><div class="num">[^<]+</div><div class="lbl">Avg AI Cost[^<]*</div></div>',
        f'<div class="summary-card amber"><div class="num">{avg_cost_str}</div><div class="lbl">{cost_lbl}</div></div>',
        static_cards_html
    )

    return dynamic + updated_static


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


# ── HTML patcher ──────────────────────────────────────────────────────────────

def patch_html(html, all_tickets, epic_titles):
    """Rebuild all dynamic sections of the dashboard HTML."""

    # ── 1. Initiatives section ─────────────────────────────────────────────
    # Route tickets to initiatives
    init_ticket_map  = defaultdict(lambda: defaultdict(list))  # slug → epic_key → [tickets]
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

    # Build all 25 initiative blocks from config — never reads existing HTML blocks.
    section_start_tag = '<div id="init-section-body">'
    section_end_tag   = '</div><!-- end init-section-body -->'
    section_start = html.find(section_start_tag)
    section_end   = html.find(section_end_tag)
    if section_start < 0 or section_end < 0:
        print("  ⚠ could not find init-section-body boundaries", file=sys.stderr)
    else:
        new_blocks = []
        for slug, prod_key, iproj, ititle, _ in INITIATIVES:
            tickets_by_epic = init_ticket_map.get(slug, {})
            all_init_tickets = [t for ts in tickets_by_epic.values() for t in ts]
            icounts_html = build_icounts(all_init_tickets)

            head = (
                f'    <div class="initiative-block" data-init="{slug}">\n'
                f'    <div class="initiative-head" onclick="toggleInit(this)">\n'
                f'      <span class="iarrow">▶</span>\n'
                f'      <span class="ikey"><a href="{JIRA_URL}/browse/{prod_key}" target="_blank" '
                f'style="color:inherit;text-decoration:none">{prod_key}</a></span>\n'
                f'      <span class="iproj">{html_lib.escape(iproj)}</span>\n'
                f'      <span class="ititle">{html_lib.escape(ititle)}</span>\n'
                f'      <div class="icounts">\n        {icounts_html}\n      </div>\n'
                f'    </div>\n'
            )
            body = build_initiative_body(slug, tickets_by_epic, epic_titles)
            new_blocks.append(
                head + body
                + f'    </div><!-- end initiative-block data-init={slug} -->\n\n'
            )

        new_section = (
            section_start_tag + '\n'
            + ''.join(new_blocks)
            + '  ' + section_end_tag
        )
        html = html[:section_start] + new_section + html[section_end + len(section_end_tag):]

    # ── 2. Summary bar ─────────────────────────────────────────────────────
    bar_m = re.search(
        r'(<div class="summary-bar"[^>]*>)(.*?)(</div>)\s*\n\s*(<div id="init-section-wrap")',
        html, re.DOTALL
    )
    if bar_m:
        static_cards = re.sub(
            r'\s*<div class="summary-card [^"]*"><div class="num">[^<]*</div><div class="lbl">(?:Total Tickets|Done|In Progress.*?|To Do|Initiatives|Authors)</div></div>',
            '', bar_m.group(2), flags=re.DOTALL
        )
        new_bar_content = build_summary_bar(all_tickets, static_cards)
        html = html[:bar_m.start(2)] + "\n" + new_bar_content + "\n  " + html[bar_m.end(2):]

    # ── 3. By-author section ────────────────────────────────────────────────
    ba_start = html.find('id="by-author-body"')
    ba_open  = html.find('>', ba_start) + 1
    ba_end   = html.find('</div><!-- end by-author-body')
    if ba_start > 0 and ba_end > 0:
        new_ba = "\n" + build_author_section(all_tickets)
        html = html[:ba_open] + new_ba + html[ba_end:]

    # ── 4. Created leaderboard ──────────────────────────────────────────────
    created_h2 = html.find('<h2>🏆 Top 5 Authors — Most FlowForge Tickets Created')
    done_h2    = html.find('<h2>✅ Top 5 Authors — Most FlowForge Tickets Done')
    if created_h2 > 0 and done_h2 > 0:
        html = html[:created_h2] + build_created_leaderboard(all_tickets) + html[done_h2:]

    # ── 5. Done leaderboard ─────────────────────────────────────────────────
    done_h2  = html.find('<h2>✅ Top 5 Authors — Most FlowForge Tickets Done')
    top10_h2 = html.find('<h2>🏅 Top 10 Developers — Most FlowForge Tickets Done')
    if done_h2 > 0 and top10_h2 > 0:
        html = html[:done_h2] + build_done_leaderboard(all_tickets) + html[top10_h2:]

    # ── 6. Top 10 Developers Done leaderboard ──────────────────────────────
    top10_h2    = html.find('<h2>🏅 Top 10 Developers — Most FlowForge Tickets Done')
    active_h2   = html.find('<h2>⚡ Top 10 Developers')
    if top10_h2 > 0 and active_h2 > 0:
        html = html[:top10_h2] + build_top10_devs(all_tickets) + html[active_h2:]

    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Regenerate FlowForge dashboard from Jira")
    parser.add_argument("--dry-run", action="store_true", help="Print stats only, don't write file")
    args = parser.parse_args()

    if not JIRA_EMAIL or not JIRA_TOKEN:
        sys.exit("Set JIRA_EMAIL and JIRA_API_TOKEN environment variables (or use a .env file)")

    print("Fetching FlowForge tickets from Jira…")
    tickets = fetch_all_flowforge_tickets()
    # Exclude Closed tickets
    tickets = [t for t in tickets if t["status"] != "Closed"]
    print(f"  {len(tickets)} tickets (Closed excluded)")

    # Fetch epic titles for all known epics
    all_epic_keys = list({e for _, _, _, _, epics in INITIATIVES for e in epics if e})
    print(f"Fetching titles for {len(all_epic_keys)} epics…")
    epic_titles = fetch_epic_titles(all_epic_keys)

    if args.dry_run:
        by_cat = defaultdict(int)
        for t in tickets:
            by_cat[t["cat"]] += 1
        print(f"  Done: {by_cat['Done']}  In Progress: {by_cat['In Progress']}  To Do: {by_cat['To Do']}")
        costs = [t["ai_cost"] for t in tickets if t["ai_cost"] > 0]
        if costs:
            print(f"  Avg AI cost: ${sum(costs)/len(costs):.2f} ({len(costs)} tickets with cost)")
        return

    with open(DASHBOARD_FILE) as f:
        html = f.read()

    print("Patching HTML…")
    new_html = patch_html(html, tickets, epic_titles)

    with open(DASHBOARD_FILE, "w") as f:
        f.write(new_html)

    print(f"Written: {DASHBOARD_FILE}")
    print(f"  {len(html):,} → {len(new_html):,} chars (delta {len(new_html)-len(html):+,})")


if __name__ == "__main__":
    main()
