#!/usr/bin/env python3
"""Build index.html from data/arena.sqlite and data/prices.json (stdlib only).

Reads the `latest` view, keeps the variant arena.ai shows by default plus the
raw (no style control) twin for text/vision/search/document, drops retired
categories, merges model names across arenas into one canonical key, and
embeds the result as compact JSON into scripts/page_template.html.

Run:  python3 -I scripts/build_page.py              # writes index.html (standalone page)
      python3 -I scripts/build_page.py --report     # also prints every name merge
      python3 -I scripts/build_page.py --fragment --out page.html
                                                    # body-only HTML, no doctype, for embedding
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STALE_DAYS = 60

ARENAS = [  # display order (matrix columns follow it)
    ("text", "Text"), ("webdev", "WebDev"), ("vision", "Vision"), ("search", "Search"),
    ("document", "Document"), ("text_to_image", "Text to image"), ("image_edit", "Image edit"),
    ("text_to_video", "Text to video"), ("image_to_video", "Image to video"),
    ("video_edit", "Video edit"), ("agent", "Agent"),
]
DROP_CATS = {("webdev", "webdev")}  # exact duplicate of webdev/overall

TEXT_CORE = ["overall", "coding", "hard_prompts", "math", "creative_writing",
             "instruction_following", "multi_turn", "longer_query", "expert"]
TEXT_MORE = ["hard_prompts_english", "exclude_ties"]
LANG_ORDER = ["english", "non_english", "chinese", "spanish", "french", "german",
              "russian", "japanese", "korean", "polish"]
WEBDEV_ORDER = ["overall", "webdev-html", "webdev-react", "image_to_webdev"]

LABELS = {
    "overall": "Overall", "coding": "Coding", "hard_prompts": "Hard prompts",
    "hard_prompts_english": "Hard prompts (EN)", "exclude_ties": "Excluding ties",
    "math": "Math", "creative_writing": "Creative writing",
    "instruction_following": "Instruction following", "multi_turn": "Multi-turn",
    "longer_query": "Longer query", "expert": "Expert", "non_english": "Non-English",
    "industry_business_and_management_and_financial_operations": "Business & finance",
    "industry_entertainment_and_sports_and_media": "Entertainment & media",
    "industry_legal_and_government": "Legal & government",
    "industry_life_and_physical_and_social_science": "Life & social science",
    "industry_mathematical": "Mathematical",
    "industry_medicine_and_healthcare": "Medicine & health",
    "industry_software_and_it_services": "Software & IT",
    "industry_writing_and_literature_and_language": "Writing & literature",
    "webdev-html": "HTML", "webdev-react": "React", "image_to_webdev": "Image to web",
    "creative_writing_vision": "Creative writing", "entity_recognition": "Entity recognition",
    "ocr": "OCR", "3d_modeling": "3D modeling", "commercial_design": "Commercial design",
    "text_rendering": "Text rendering", "multi_image_edit": "Multi-image",
    "multi_image_edit_agentic": "Multi-image agentic", "photorealistic": "Photorealistic",
}

# Default-visible columns; everything else starts hidden but can be switched on.
DEFAULT_ON = {("text", c) for c in TEXT_CORE} | {("webdev", c) for c in WEBDEV_ORDER} | {
    (a, "overall") for a, _ in ARENAS if a not in ("text", "webdev")}

FLAGSHIP_ORGS = ["anthropic", "openai", "google", "xai", "deepseek", "alibaba", "moonshot", "zai"]


def label(cat: str) -> str:
    return LABELS.get(cat) or cat.replace("_", " ").capitalize()


def group_of(arena: str, cat: str) -> tuple[str, str]:
    """-> (group id, group label). Groups are the collapsible column sets."""
    if arena == "text":
        if cat in TEXT_CORE:
            return "text", "Text"
        if cat.startswith("industry_"):
            return "text-industry", "Text by industry"
        if cat in TEXT_MORE:
            return "text-more", "Text, other cuts"
        return "text-lang", "Text by language"
    return arena, dict(ARENAS)[arena]


def cat_sort_key(arena: str, cat: str):
    a = [x for x, _ in ARENAS].index(arena)
    if arena == "text":
        g = group_of(arena, cat)[0]
        gi = ["text", "text-more", "text-industry", "text-lang"].index(g)
        order = TEXT_CORE if g == "text" else TEXT_MORE if g == "text-more" else LANG_ORDER
        i = order.index(cat) if cat in order else 99
        return (a, gi, i, cat)
    if arena == "webdev":
        return (a, 0, WEBDEV_ORDER.index(cat) if cat in WEBDEV_ORDER else 99, cat)
    return (a, 0, 0 if cat == "overall" else 1, cat)


# ---- name canonicalisation -------------------------------------------------

def canon(name: str) -> str:
    """Conservative cross-arena key. Keeps every parenthesised qualifier
    (reasoning level, date, harness), so "(High)" and "(Max)" never merge."""
    s = name.lower().strip()
    s = re.sub(r"[\s_\-]+", " ", s)                 # "gpt-5.5" / "gpt_5.5" -> "gpt 5.5"
    s = re.sub(r"(?<=[a-z])\.(?=\d)", " ", s)       # "flux.2" -> "flux 2"
    s = re.sub(r"(?<=[a-z]) (?=\d)", "", s)         # "gpt 5.5" -> "gpt5.5", "qwen 3.8" -> "qwen3.8"
    s = re.sub(r"\(\s*", "(", s)
    s = re.sub(r"\s*\)", ")", s)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s.strip()


# ---- model families ---------------------------------------------------------
# A family is one model with its effort levels, token budgets, search/harness
# setups, precision and date stamps folded together. Only parenthesised
# qualifiers (and a few trailing stamps) are removed; words that name a
# different model (Sol/Luna, Flash/Pro, mini, Codex, Chat, Instant, -Thinking
# as a released model) stay in the name.

_DATE = (r"\d{8}|\d{6}|\d{4}|\d{3}|\d{2}-\d{2}|\d{2}-\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{2}"
         r"|(?:jan|feb|mar|apr|may|june?|july?|aug|sep|oct|nov|dec)[a-z]* \d{4}")
QUALIFIER = re.compile(
    r"^(?:"
    r"low|medium|high|x-?high|max|minimal|none|default"                     # effort
    r"|thinking|non-?thinking|no-?thinking|reasoning|non-?reasoning|instant"  # think modes
    r"|(?:thinking )?\d+k"                                                    # budgets / 2K res
    r"|search|web search|grounding|codex harness|online|dev api"              # setups
    r"|bf16|fp8|fp16|nvfp4|int4"                                              # precision
    r"|\d{3,4}p|high res|high fidelity|quality|audio|fal|prompt extend"       # media settings
    rf"|{_DATE}"
    r")$", re.I)
TRAIL_STAGE = re.compile(r"[\s\-]+(preview|beta(?:\s+\d+)?)$", re.I)
TRAIL_DATE = re.compile(r"[\s\-]+(\d{8})$")
SLUG_TRAIL = re.compile(
    r"-(high|medium|low|xhigh|max|minimal|thinking|no-thinking|non-thinking|preview|beta"
    r"|\d{8}|\d{4}-\d{2}-\d{2}|\d{2}-\d{4}|\d{2}-\d{2}|\d{4}|\d{3})$", re.I)
NICE = {"xhigh": "xHigh", "x-high": "xHigh", "non-thinking": "Non-Thinking", "no-thinking": "Non-Thinking",
        "non-reasoning": "Non-Reasoning", "codex harness": "Codex Harness", "web search": "Web Search"}


def _nice(tok: str) -> str:
    t = tok.strip()
    if t.lower() in NICE:
        return NICE[t.lower()]
    return t[0].upper() + t[1:] if t and t.islower() else t


def is_slug(name: str) -> bool:
    return " " not in name and "-" in name and name == name.lower()


def family_parts(name: str) -> tuple[str, list[str]]:
    """Pretty name -> (family display name, dropped qualifiers)."""
    dropped: list[str] = []

    def paren(m):
        keep = []
        for tok in m.group(1).split(","):
            t = tok.strip()
            if not t:
                continue
            (dropped if QUALIFIER.match(t) else keep).append(t)
        return f" ({', '.join(keep)})" if keep else ""

    s = re.sub(r"\s*\(([^()]*)\)", paren, name).strip()
    while True:
        m = TRAIL_DATE.search(s) or TRAIL_STAGE.search(s)
        if not m:
            break
        dropped.append(m.group(1))
        s = s[:m.start()].rstrip()
    return re.sub(r"\s+", " ", s), [_nice(t) for t in dropped]


def slug_candidates(name: str) -> list[tuple[str, list[str]]]:
    """Slug name -> successively stripped (name, dropped) pairs, least stripped first."""
    out, s, dropped = [(name, [])], name, []
    while True:
        m = SLUG_TRAIL.search(s)
        if not m:
            return out
        dropped = [_nice(m.group(1))] + dropped
        s = s[:m.start()]
        out.append((s, list(dropped)))


def org_slug(org: str | None) -> str:
    return re.sub(r"[\s_]+", "-", (org or "").strip().lower())


def fnv36(s: str, n: int) -> str:
    h = 0x811C9DC5
    for b in s.encode():
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    out = ""
    while h:
        h, r = divmod(h, 36)
        out = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + out
    return out.rjust(7, "0")[-n:]


def r1(x):
    return None if x is None else round(x, 1)


def pnorm(s: str) -> str:
    return re.sub(r"[^a-z0-9+]", "", (s or "").lower())


def load_prices(path: Path):
    """data/prices.json -> (records, fetched_at) or (None, None) when missing/unreadable.
    Accepts {"fetched_at": ..., "records": [...]} or a bare list of records."""
    try:
        recs = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if isinstance(recs, dict):
        return (recs.get("records") if isinstance(recs.get("records"), list) else None), recs.get("fetched_at")
    return (recs if isinstance(recs, list) else None), None


def effort_label(model: str) -> str:
    """'Claude Opus 5.5 (High)' -> 'High'; date stamps dropped; '' when none."""
    _, dropped = family_parts(model)
    keep = [t for t in dropped if not re.fullmatch(r"[\d-]+", t)]
    return ", ".join(keep)


# ---- effort entries ---------------------------------------------------------
# The page's unit of comparison is model + effort level. Of a variant's dropped
# qualifiers, effort words, think modes and thinking budgets name the effort;
# dates, Preview/Beta stamps and setups (Search, Grounding, Codex Harness,
# precision, media settings) are folded together so cells fill across arenas.
EFFORT_TOK = re.compile(
    r"^(?:low|medium|high|x-?high|max|minimal|none|thinking|non-?thinking|no-?thinking"
    r"|reasoning|non-?reasoning|instant|thinking \d+k)$", re.I)
BUDGET_TOK = re.compile(r"^\d+k$", re.I)  # "32K" is a thinking budget next to an effort, else a resolution
STAMP_TOK = re.compile(rf"^(?:{_DATE}|preview|beta(?:\s+\d+)?)$", re.I)
EFFORT_LEVEL = {"minimal": 1, "none": 1, "non-thinking": 1, "no-thinking": 1, "nonthinking": 1,
                "non-reasoning": 1, "nonreasoning": 1, "instant": 1, "low": 2, "medium": 3,
                "high": 4, "thinking": 4, "reasoning": 4, "xhigh": 5, "x-high": 5, "max": 6}


def split_qualifiers(dropped: list[str]) -> tuple[list[str], list[str]]:
    """Dropped qualifiers -> (effort tokens, setup tokens). Date and stage stamps are discarded."""
    named = any(EFFORT_TOK.match(t) for t in dropped)
    eff, setup = [], []
    for t in dropped:
        if EFFORT_TOK.match(t) or (named and BUDGET_TOK.match(t)):
            eff.append(t)
        elif not STAMP_TOK.match(t):
            setup.append(t)
    return eff, setup


def effort_level(eff: list[str]) -> tuple[int, int]:
    """-> (level 0-6, thinking budget in K) for ordering and shading. 0 = no effort named."""
    lvl, budget = 0, 0
    for t in eff:
        k = t.lower()
        m = re.search(r"(\d+)k$", k)
        if m:
            budget = int(m.group(1))
            lvl = max(lvl, 4)
        lvl = max(lvl, EFFORT_LEVEL.get(k, 0))
    return lvl, budget


def price_row(rec: dict, name_to_vi: dict[str, int]):
    """Compact per-family price record (see decode() in the template):
    [in, out, blend, ctx, tok/s, ttft_s, flags, agent, note, [models.dev id, OpenRouter id]]
    flags: 1 = price from OpenRouter, 2 = OpenRouter top-level listed price (maybe third-party
    host), 4 = listed as free (price unknown). agent: [[effort, $/task, out tokens, variant idx]].
    API ids are null when unknown; the export dialog shows them so an agent can call the model."""
    inp, out, blend = rec.get("input_per_m"), rec.get("output_per_m"), rec.get("blended_per_m")
    notes = rec.get("notes") or ""
    flags = (1 if rec.get("source") == "openrouter" else 0) | (2 if "OpenRouter listed price" in notes else 0)
    if not inp and not out:
        flags |= 4
        inp = out = blend = None
    agent = []
    for a in rec.get("agent_cost_per_task") or []:
        agent.append([effort_label(a["model"]) or "Default", round(a["cost_per_task_p50"], 3),
                      a.get("output_tokens_per_task_p50"), name_to_vi.get(a["model"], -1)])
    rnd = lambda v: None if v is None else round(v, 4)  # noqa: E731
    src, sid = rec.get("source"), rec.get("source_id")
    ids = [sid if src == "models.dev" else None,
           rec.get("openrouter_id") or (sid if src == "openrouter" else None)]
    return [rnd(inp), rnd(out), rnd(blend), rec.get("context_tokens"), rec.get("tokens_per_sec"),
            rec.get("ttft_s"), flags, agent, notes, ids]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "arena.sqlite")
    ap.add_argument("--template", type=Path, default=ROOT / "scripts" / "page_template.html")
    ap.add_argument("--out", type=Path, default=ROOT / "index.html")
    ap.add_argument("--fragment", action="store_true",
                    help="write the template as is (no doctype/head wrapper), for embedding")
    ap.add_argument("--prices", type=Path, default=ROOT / "data" / "prices.json")
    ap.add_argument("--report", action="store_true", help="print every multi-name merge")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT arena, variant, style_control, site_default, category, snapshot_date, model,
               model_seq, org, score_type, rank, score, ci_lower, ci_upper, votes,
               source_revision, fetched_at
        FROM latest
        WHERE site_default = 1
           OR (variant = 'raw' AND arena IN (SELECT arena FROM latest WHERE variant='style_control'))
    """).fetchall()
    if not rows:
        print("no rows in `latest`; run scripts/fetch_arena.py first", file=sys.stderr)
        return 1

    # ---- stale categories ----
    newest = collections.defaultdict(str)
    for r in rows:
        newest[r["arena"]] = max(newest[r["arena"]], r["snapshot_date"])
    cat_date = {}
    for r in rows:
        k = (r["arena"], r["category"])
        cat_date[k] = max(cat_date.get(k, ""), r["snapshot_date"])
    dropped = []
    keep_cats = set()
    for (a, c), d in cat_date.items():
        age = (dt.date.fromisoformat(newest[a]) - dt.date.fromisoformat(d)).days
        if (a, c) in DROP_CATS:
            dropped.append((a, c, d, "duplicate of overall"))
        elif age > STALE_DAYS:
            dropped.append((a, c, d, f"{age} days older than newest {a} board"))
        else:
            keep_cats.add((a, c))
    rows = [r for r in rows if (r["arena"], r["category"]) in keep_cats]

    # ---- canonical keys, with a per-board collision guard ----
    def base_key(r):
        k = canon(r["model"])
        return k if r["model_seq"] == 0 else f"{k}#{r['model_seq'] + 1}"

    board_names = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in rows:
        board_names[(r["arena"], r["variant"], r["category"])][base_key(r)].add(r["model"])
    unsafe = {}  # key -> names that collide inside one leaderboard (never merge those)
    for names_by_key in board_names.values():
        for k, names in names_by_key.items():
            if len(names) > 1:
                unsafe.setdefault(k, set()).update(names)

    def key_of(r):
        k = base_key(r)
        if k in unsafe:
            return f"{k}|{r['model']}"
        return k

    name_count = collections.defaultdict(collections.Counter)
    org_count = collections.defaultdict(collections.Counter)
    for r in rows:
        k = key_of(r)
        name_count[k][r["model"]] += 1
        if r["org"]:
            org_count[k][org_slug(r["org"])] += 1

    keys = list(name_count)
    display = {}
    for k in keys:
        nm = max(name_count[k].items(), key=lambda kv: (kv[1], any(ch.isupper() for ch in kv[0]), kv[0]))[0]
        if "#" in k.split("|")[0]:
            nm = f"{nm} (entry {k.split('|')[0].rsplit('#', 1)[1]})"
        display[k] = nm

    # ---- categories ----
    cats = sorted(keep_cats, key=lambda ac: cat_sort_key(*ac))
    cat_index = {ac: i for i, ac in enumerate(cats)}
    sc_arenas = {r["arena"] for r in rows if r["variant"] == "style_control"}

    # text overall rank (site default) for ordering models
    text_rank = {}
    best_pct = collections.defaultdict(lambda: 9.0)
    board_n = collections.Counter()
    for r in rows:
        if r["site_default"]:
            board_n[(r["arena"], r["category"])] += 1
    for r in rows:
        if not r["site_default"]:
            continue
        k = key_of(r)
        if (r["arena"], r["category"]) == ("text", "overall"):
            text_rank[k] = r["rank"]
        if r["category"] == "overall":
            n = board_n[(r["arena"], "overall")]
            best_pct[k] = min(best_pct[k], (r["rank"] - 1) / max(1, n - 1))
    keys.sort(key=lambda k: (text_rank.get(k, 10_000), best_pct[k], display[k].lower()))
    kidx = {k: i for i, k in enumerate(keys)}

    orgs = sorted({o for k in keys for o in org_count[k]} | {""})
    oidx = {o: i for i, o in enumerate(orgs)}

    ids, seen = [], {}
    for k in keys:
        n = 5
        mid = fnv36(k, n)
        while mid in seen:
            n += 1
            mid = fnv36(k, n)
        seen[mid] = k
        ids.append(mid)

    models = []
    for k, mid in zip(keys, ids):
        org = org_count[k].most_common(1)[0][0] if org_count[k] else ""
        models.append([display[k], oidx[org], mid])

    # ---- families: fold effort levels / setups / dates into one entry ----
    def entry_note(k):
        base = k.split("|")[0]
        return f"entry {base.rsplit('#', 1)[1]}" if "#" in base else ""

    fam_of, via_of, drop_of, fam_names = {}, {}, {}, collections.defaultdict(collections.Counter)
    slug_keys = []
    for k in keys:
        names = name_count[k]
        pretty = [n for n in names if not is_slug(n)]
        if not pretty:
            slug_keys.append(k)
            continue
        src = max(pretty, key=lambda n: (names[n], n))
        fd, dropped = family_parts(src)
        fk = canon(fd)
        fam_of[k] = fk
        drop_of[k] = dropped
        via_of[k] = ", ".join(dropped + ([entry_note(k)] if entry_note(k) else []))
        fam_names[fk][fd] += sum(names.values())
    pretty_fams = set(fam_of.values())
    for k in slug_keys:
        nm = max(name_count[k], key=lambda n: (name_count[k][n], n))
        cands = slug_candidates(nm)
        hit = next(((s, d) for s, d in cands if canon(s) in pretty_fams), None)
        s, d = hit or cands[0]
        fk = canon(s)
        fam_of[k] = fk
        drop_of[k] = d
        via_of[k] = ", ".join(d + ([entry_note(k)] if entry_note(k) else []))
        fam_names[fk][s] += 0 if hit else sum(name_count[k].values())

    fam_members = collections.defaultdict(list)
    for k in keys:  # keys are already in rank order, so members are too
        fam_members[fam_of[k]].append(k)

    def fam_sort(fk):
        ks = fam_members[fk]
        return (min(text_rank.get(k, 10_000) for k in ks), min(best_pct[k] for k in ks), fk)

    fam_keys = sorted(fam_members, key=fam_sort)
    used_ids = set(ids)
    fams = []
    for fk in fam_keys:
        ks = fam_members[fk]
        nm = max(fam_names[fk].items(), key=lambda kv: (kv[1], any(ch.isupper() for ch in kv[0]), " " in kv[0], kv[0]))[0]
        oc = collections.Counter()
        for k in ks:
            oc.update(org_count[k])
        org = oc.most_common(1)[0][0] if oc else ""
        n = 5
        fid = fnv36("family:" + fk, n)
        while fid in used_ids:
            n += 1
            fid = fnv36("family:" + fk, n)
        used_ids.add(fid)
        fams.append([nm, oidx[org], fid, [kidx[k] for k in ks], [via_of[k] for k in ks]])

    # ---- effort entries: one per family + effort level (setups and dates folded in) ----
    effs = []
    for fi, fk in enumerate(fam_keys):
        groups_ = {}
        for k in fam_members[fk]:  # rank order
            eff, setup = split_qualifiers(drop_of.get(k, []))
            lab = ", ".join(eff)
            if entry_note(k):
                lab = f"{lab or 'Default'}, {entry_note(k)}"
            g = groups_.setdefault(lab.lower(), {"label": lab, "eff": eff, "members": [], "setups": []})
            g["members"].append(kidx[k])
            g["setups"].append(", ".join(setup))
        multi_eff = len(groups_) > 1
        rows_ = []
        for ek, g in groups_.items():
            lvl, budget = effort_level(g["eff"])
            # no effort named: "Default" when the model also has named levels, no tag otherwise
            label_ = g["label"] or ("Default" if multi_eff else "")
            n = 5
            eid = fnv36(f"effort:{fk}|{ek}", n)
            while eid in used_ids:
                n += 1
                eid = fnv36(f"effort:{fk}|{ek}", n)
            used_ids.add(eid)
            rows_.append(((lvl, budget, label_.lower()), [fi, label_, lvl, g["members"], g["setups"], eid]))
        effs += [r for _, r in sorted(rows_, key=lambda x: x[0])]

    # ---- prices: join data/prices.json on exact Arena names, then normalized family name ----
    prices_out, price_report = None, None
    recs, prices_at = load_prices(args.prices)
    if recs:
        by_name = {}
        for ri, rec in enumerate(recs):
            for n in rec.get("arena_models") or []:
                by_name.setdefault(n, ri)
        by_norm = {}
        for ri, rec in enumerate(recs):
            by_norm.setdefault((pnorm(rec.get("family")), rec.get("org") or ""), ri)
            by_norm.setdefault((pnorm(rec.get("family")), "*"), ri)
        name_to_vi = {n: kidx[k] for k in keys for n in name_count[k]}
        prices_out, used, how = [], set(), collections.Counter()
        for fk, f in zip(fam_keys, fams):
            votes = collections.Counter(by_name[n] for k in fam_members[fk] for n in name_count[k] if n in by_name)
            # most Arena names wins; ties go to the record named like the family ("Hy4" over "Hy4 preview")
            ri = max(votes, key=lambda r: (votes[r], pnorm(recs[r].get("family")) == pnorm(f[0]), -r)) if votes else None
            via = "name" if votes else None
            if ri is None:
                hit = by_norm.get((pnorm(f[0]), orgs[f[1]])) or by_norm.get((pnorm(f[0]), "*"))
                ri, via = (hit, "family") if hit is not None else (None, None)
            if ri is None:
                prices_out.append(0)
                continue
            used.add(ri)
            how[via] += 1
            prices_out.append(price_row(recs[ri], name_to_vi))
        price_report = (len(recs), len(used), how, [recs[i]["family"] for i in range(len(recs)) if i not in used])

    # ---- per-board rows: flat [model, rank, score, lo, hi, votes, ...] ----
    boards = {i: {"d": [], "r": []} for i in range(len(cats))}
    stype = {}
    for r in sorted(rows, key=lambda r: (r["rank"] or 0)):
        ci = cat_index[(r["arena"], r["category"])]
        slot = "d" if r["site_default"] else "r"
        st = r["score_type"]
        stype[r["arena"]] = st
        rnd = (lambda x: None if x is None else round(x, 4)) if st != "bt" else r1
        boards[ci][slot] += [kidx[key_of(r)], r["rank"], rnd(r["score"]), rnd(r["ci_lower"]),
                             rnd(r["ci_upper"]), int(r["votes"] or 0)]

    arena_ids = [a for a, _ in ARENAS if any(c[0] == a for c in cats)]
    groups, gseen = [], set()
    cat_out = []
    for i, (a, c) in enumerate(cats):
        g, gl = group_of(a, c)
        if g not in gseen:
            gseen.add(g)
            groups.append([g, gl, arena_ids.index(a)])
        cat_out.append([arena_ids.index(a), c, label(c), [x[0] for x in groups].index(g),
                        cat_date[(a, c)], int((a, c) in DEFAULT_ON)])

    meta_row = con.execute("SELECT source_revision, MAX(fetched_at) FROM scores").fetchone()
    data = {
        "v": 1,
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        "rev": (meta_row[0] or "")[:12],
        "fetched": (meta_row[1] or "")[:10],
        "arenas": [[a, dict(ARENAS)[a], stype.get(a, "bt"), int(a in sc_arenas), newest[a]] for a in arena_ids],
        "groups": groups,
        "orgs": orgs,
        "models": models,
        "fams": fams,
        "effs": effs,  # [family idx, effort label, level 0-6, [variant idx], [setup per variant], id]
        "cats": cat_out,
        "rows": [[boards[i]["d"], boards[i]["r"]] for i in range(len(cats))],
        "flagshipOrgs": FLAGSHIP_ORGS,
    }
    if prices_out is not None:
        data["prices"] = prices_out  # aligned with fams; 0 = no price record
        data["pricesAt"] = prices_at or dt.datetime.fromtimestamp(
            args.prices.stat().st_mtime, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    payload = payload.replace("</", "<\\/")

    tpl = args.template.read_text(encoding="utf-8")
    if "/*__ARENA_DATA__*/null" not in tpl:
        print("template is missing the /*__ARENA_DATA__*/null placeholder", file=sys.stderr)
        return 1
    html = tpl.replace("/*__ARENA_DATA__*/null", payload)
    if not args.fragment:
        html = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
                f"{html.rstrip()}\n</html>\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    # ---- report ----
    merged = {k: v for k, v in name_count.items() if len(v) > 1}
    print(f"wrote {args.out}  ({args.out.stat().st_size / 1024:.0f} KB, data {len(payload) / 1024:.0f} KB)")
    print(f"models {len(models)}  categories {len(cats)}  arenas {len(arena_ids)}  "
          f"orgs {len(orgs) - 1}  models without org {sum(1 for m in models if m[1] == oidx[''])}")
    print(f"dropped categories: {len(dropped)}")
    for a, c, d, why in sorted(dropped):
        print(f"  - {a}/{c} ({d}): {why}")
    print(f"name groups merged: {len(merged)}")
    for k, v in sorted(merged.items(), key=lambda kv: kv[0])[: None if args.report else 12]:
        print(f"  {display[k]!r:48} <- {sorted(v)}")
    if unsafe:
        print(f"kept apart (same key inside one leaderboard): {len(unsafe)}")
        for k, v in unsafe.items():
            print(f"  {k!r}: {sorted(v)}")
    multi = [f for f in fams if len(f[3]) > 1]
    print(f"families: {len(fams)} from {len(models)} entries; {len(multi)} families have 2+ variants; "
          f"{len(effs)} model + effort entries")
    if price_report is None:
        print(f"prices: {args.prices} missing or unreadable; page hides the price UI")
    else:
        n_rec, n_used, how, unused = price_report
        text_top = [f for f in fams if any(text_rank.get(keys[vi], 10_000) <= 50 for vi in f[3])]
        tt_priced = [f for f in text_top if prices_out[fams.index(f)]]
        print(f"prices: {n_used}/{n_rec} price records joined ({how['name']} on Arena names, "
              f"{how['family']} on family name); {sum(1 for p in prices_out if p)} of {len(fams)} families priced; "
              f"text top-50 families priced: {len(tt_priced)}/{len(text_top)}")
        if unused:
            print(f"  price records not joined: {', '.join(unused)}")
        miss = [f[0] for f in text_top if not prices_out[fams.index(f)]]
        if miss:
            print(f"  text top-50 families without price: {', '.join(miss)}")
    if args.report:
        by_org = collections.defaultdict(list)
        for f in multi:
            by_org[orgs[f[1]]].append(f)
        for o in FLAGSHIP_ORGS + sorted(set(by_org) - set(FLAGSHIP_ORGS)):
            if o not in by_org:
                continue
            print(f"  == {o or '(no org)'}")
            for f in by_org[o]:
                parts = [f"{models[vi][0]}" + (f" [{via}]" if via else "") for vi, via in zip(f[3], f[4])]
                print(f"    {f[0]!r:34} <- " + " | ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
