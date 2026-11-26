#!/usr/bin/env python3
"""Fetch price, context window and speed for Arena model families.

Writes data/prices.json: one record per Arena *family* (model name with
effort/setup qualifiers and date stamps stripped), joined to:

  price + context + release date
    1. models.dev  (https://models.dev/api.json, no key) - first-party list
       price from the model maker's own provider entry (e.g. zai, moonshotai).
    2. OpenRouter endpoint run by the model maker itself
       (/api/v1/models/<id>/endpoints, official API).
    3. OpenRouter /api/v1/models top-level price (may be the cheapest
       third-party host or a promo; flagged in `notes`).
  speed (tokens_per_sec, ttft_s)
    OpenRouter per-endpoint 30-minute stats (p50 throughput tok/s, p50
    time-to-first-token ms), from one of:
      - the official endpoints API when OPENROUTER_API_KEY is set (the API
        returns null stats without a key). Mean of each endpoint's p50.
      - opt-in fallback: --scrape-pages (or OPENROUTER_SCRAPE_PAGES=1) parses
        the public model pages (https://openrouter.ai/<id>), which embed the
        same stats plus request counts (request-weighted mean). OpenRouter's
        Terms of Service (section 7) prohibit scraping the site, so this is
        off by default; prefer the API key.
    Without either, speed is left empty.
  agent cost per task
    data/arena.sqlite, arena='agent' variant='aggregate' (per effort level).

Matching is conservative: normalized exact name match within the maker's
OpenRouter / models.dev namespace, plus OVERRIDES below. No fuzzy guessing.

Usage:
  python3 scripts/fetch_prices.py            # fetch (uses cache < 6h old)
  OPENROUTER_API_KEY=... python3 scripts/fetch_prices.py   # + speed stats
  python3 scripts/fetch_prices.py --offline  # rebuild from raw/prices cache
  python3 scripts/fetch_prices.py --show "Claude Opus 5.5" "GLM-5.3"
Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "arena.sqlite"
OUT = ROOT / "data" / "prices.json"
RAW = ROOT / "raw" / "prices"
STATS_DIR = RAW / "openrouter_stats"

UA = "Mozilla/5.0 (compatible; model-price-fetcher/1.0)"
OR_MODELS_URL = "https://openrouter.ai/api/v1/models"
OR_PAGE_URL = "https://openrouter.ai/{id}"
OR_ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{id}/endpoints"
# endpoint-cache subfolders: "api" = keyed API (has speed), "page" = scraped
# model pages (has speed), "api-public" = unauthenticated API (prices only)
STATS_MODES = ("api", "page", "api-public")
SPEED_SOURCE = {
    "api": "openrouter-api p50 (30 min, mean across hosts)",
    "page": "openrouter-page p50 (30 min, request-weighted)",
}
MODELS_DEV_URL = "https://models.dev/api.json"

LLM_ARENAS = ("text", "webdev", "vision", "search", "document", "agent")

# Arena org -> (OpenRouter id prefixes, models.dev provider keys, OpenRouter
# provider_name values that count as "first party").
ORGS: dict[str, tuple[list[str], list[str], list[str]]] = {
    "anthropic": (["anthropic"], ["anthropic"], ["Anthropic"]),
    "google": (["google"], ["google"], ["Google AI Studio", "Google"]),
    "openai": (["openai"], ["openai"], ["OpenAI"]),
    "xai": (["x-ai"], ["xai"], ["xAI"]),
    "deepseek": (["deepseek"], ["deepseek"], ["DeepSeek"]),
    "alibaba": (["qwen"], ["alibaba"], ["Alibaba"]),
    "moonshot": (["moonshotai"], ["moonshotai"], ["Moonshot AI", "MoonshotAI"]),
    "zai": (["z-ai"], ["zai", "zhipuai"], ["Z.AI"]),
    "meta": (["meta", "meta-llama"], ["meta"], ["Meta"]),
    "xiaomi": (["xiaomi"], ["xiaomi"], ["Xiaomi"]),
    "minimax": (["minimax"], ["minimax"], ["Minimax", "MiniMax"]),
    "mistral": (["mistralai"], ["mistral"], ["Mistral"]),
    "tencent": (["tencent"], [], ["Tencent"]),
    "nvidia": (["nvidia"], [], ["NVIDIA"]),
    "upstage": (["upstage"], [], ["Upstage"]),
    "stepfun": (["stepfun"], [], ["StepFun"]),
    "thinky": (["thinkingmachines"], [], ["Thinking Machines"]),
    "amazon": (["amazon"], [], ["Amazon Bedrock"]),
    "cohere": (["cohere"], [], ["Cohere"]),
    "perplexity": (["perplexity"], [], ["Perplexity"]),
    "baidu": (["baidu"], [], ["Baidu"]),
    "bytedance": (["bytedance-seed", "bytedance"], [], ["ByteDance", "Seed"]),
    "reflection": (["reflection"], [], ["Reflection"]),
    "ibm": (["ibm-granite"], [], ["IBM"]),
}

# Hand-checked family -> OpenRouter id for names that don't normalize equal.
# Value None = known to have no clean match (skip). Keep this small.
OVERRIDES: dict[str, str | None] = {
    "Grok 4.20 Beta 1": "x-ai/grok-4.20",
    "Mistral Large 4": "mistralai/mistral-large-4-0",
    "Mistral Medium 3.5": "mistralai/mistral-medium-3-5",
    "Solar Pro 4": "upstage/solar-pro4",
    "Nemotron 3 Ultra": "nvidia/nemotron-3-ultra-550b-a55b",
    "Gemini 3 Flash": "google/gemini-3-flash-preview",
    # price stays models.dev alibaba/qwen3.8-max; OpenRouter only hosts the 0902 snapshot
    "Qwen3.8-Max": "qwen/qwen3.8-max-0902",
}

FAMILY_NOTES = {
    "DeepSeek-V4.1-Flash": "Arena's -20261017 build is deepseek/deepseek-v4.1-flash-1017 on OpenRouter ($0.30/$1.20); price shown is the base V4.1 Flash",
    "Qwen3.8-Max": "speed from OpenRouter qwen/qwen3.8-max-0902 snapshot",
    "Gemini 3 Flash": "matched to OpenRouter gemini-3-flash-preview",
}

# --- family names -----------------------------------------------------------

_QUAL_WORDS = {
    "low", "medium", "high", "xhigh", "max", "minimal", "none", "thinking",
    "non-thinking", "nothinking", "reasoning", "non-reasoning", "search",
    "grounding", "codex harness", "codex", "harness", "default", "adaptive",
}
_QUAL_RE = re.compile(
    r"^(\d+(\.\d+)?[km]?"            # token budgets: 32K, 16000, 1M
    r"|\d{4}(-\d{2}(-\d{2})?)?"      # 0902, 2025-11, 2025-11-01
    r"|\d{6,8}"                      # 20251101
    r"|thinking[- ]?\d+[km]?"        # thinking-32k
    r"|effort[- ].*)$"
)


def _is_qual(tok: str) -> bool:
    t = tok.strip().lower()
    return t in _QUAL_WORDS or bool(_QUAL_RE.match(t))


def family_of(model: str) -> str:
    name = model.strip()
    while True:
        m = re.search(r"\s*\(([^()]*)\)\s*$", name)
        if not m or not all(_is_qual(t) for t in m.group(1).split(",")):
            break
        name = name[: m.start()].rstrip()
    # trailing date stamps: "-20260910", " 20251101", "-0902"
    name = re.sub(r"[-_ ](20\d{6}|\d{4})$", "", name)
    return name.strip()


def norm(s: str) -> str:
    # keep "+": "Command R+" and "Command R" are different models
    return re.sub(r"[^a-z0-9+]", "", s.lower().replace("plus", "+"))


# --- fetching ---------------------------------------------------------------

def http_get(url: str, timeout: int = 60, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def cached_json(path: Path, url: str, offline: bool, max_age_h: float):
    fresh = path.exists() and (time.time() - path.stat().st_mtime) < max_age_h * 3600
    if offline or fresh:
        if not path.exists():
            sys.exit(f"missing cache {path}; run without --offline")
        return json.loads(path.read_text())
    data = json.loads(http_get(url))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


_STATS_RE = re.compile(r'"stats":\{"endpoint_id":"[^"]+"')


def parse_endpoint_stats(html: str, model_id: str) -> list[dict]:
    """Pull per-provider endpoint stats out of an OpenRouter model page."""
    s = html.replace('\\"', '"')
    dec = json.JSONDecoder()
    out, prev_end = [], 0
    for m in _STATS_RE.finditer(s):
        start = m.start() + len('"stats":')
        try:
            stats, end = dec.raw_decode(s, start)
        except ValueError:
            continue
        seg = s[prev_end:m.start()]
        prev_end = end

        def last(key: str):
            hits = re.findall(r'"%s":"([^"]*)"' % key, seg)
            return hits[-1] if hits else None

        if last("model_variant_slug") != model_id or last("variant") != "standard":
            continue
        price = re.findall(r'"pricing":\{"prompt":"([^"]*)","completion":"([^"]*)"', seg)
        out.append({
            "provider": last("provider_name"),
            "prompt": float(price[-1][0]) if price else None,
            "completion": float(price[-1][1]) if price else None,
            "p50_throughput": stats.get("p50_throughput"),
            "p50_latency_ms": stats.get("p50_latency"),
            "throughput_n": stats.get("throughput_request_count") or 0,
            "latency_n": stats.get("latency_request_count") or 0,
        })
    return out


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_endpoints_api(data: dict, model_id: str) -> list[dict]:
    """Official /api/v1/models/<id>/endpoints response -> the same shape as
    parse_endpoint_stats. The API has no request counts, so every endpoint
    with a value gets weight 1."""
    out = []
    for e in (data.get("data") or {}).get("endpoints") or []:
        if e.get("model_id", model_id) != model_id:
            continue
        price = e.get("pricing") or {}
        thr = (e.get("throughput_last_30m") or {}).get("p50")
        lat = (e.get("latency_last_30m") or {}).get("p50")
        out.append({
            "provider": e.get("provider_name"),
            "prompt": _f(price.get("prompt")),
            "completion": _f(price.get("completion")),
            "p50_throughput": thr,
            "p50_latency_ms": lat,
            "throughput_n": 1 if thr is not None else 0,
            "latency_n": 1 if lat is not None else 0,
        })
    return out


def stats_mode(scrape_pages: bool) -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return "api"
    return "page" if scrape_pages else "api-public"


def endpoint_stats(model_id: str, offline: bool, max_age_h: float, mode: str) -> tuple[list[dict] | None, str | None]:
    """-> (endpoints, cache mode they came from)."""
    fname = model_id.replace("/", "__") + ".json"
    path = STATS_DIR / mode / fname

    def from_cache():
        # never fall back to scraped page data unless scraping was opted into
        allowed = [m for m in STATS_MODES if m != "page" or mode == "page"]
        for m in (mode, *[x for x in allowed if x != mode]):
            p = STATS_DIR / m / fname
            if p.exists():
                return json.loads(p.read_text()), m
        return None, None

    fresh = path.exists() and (time.time() - path.stat().st_mtime) < max_age_h * 3600
    if offline:
        return from_cache()
    if fresh:
        return json.loads(path.read_text()), mode
    try:
        if mode == "page":
            html = http_get(OR_PAGE_URL.format(id=model_id)).decode("utf-8", "replace")
            eps = parse_endpoint_stats(html, model_id)
        else:
            key = os.environ.get("OPENROUTER_API_KEY")
            hdr = {"Authorization": f"Bearer {key}"} if key and mode == "api" else None
            eps = parse_endpoints_api(json.loads(http_get(OR_ENDPOINTS_URL.format(id=model_id), headers=hdr)), model_id)
    except Exception as e:  # noqa: BLE001
        print(f"  ! endpoint fetch failed for {model_id}: {e}", file=sys.stderr)
        return from_cache()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(eps, indent=1))
    time.sleep(0.4 if mode == "page" else 0.1)
    return eps, mode


def weighted(eps: list[dict], val: str, n: str) -> float | None:
    pts = [(e[val], e[n]) for e in eps if e.get(val) is not None and e.get(n)]
    tot = sum(w for _, w in pts)
    return sum(v * w for v, w in pts) / tot if tot else None


# --- arena ------------------------------------------------------------------

def arena_families(con) -> dict[tuple[str, str], list[str]]:
    """(display family, org) -> Arena model names. Spellings that differ only in
    punctuation ("GPT 5.6 Sol" in the agent arena vs "GPT-5.6 Sol") are merged;
    the text/webdev spelling wins as the display name."""
    q = f"""SELECT model, COALESCE(org,''), MIN(CASE WHEN arena IN ('text','webdev') THEN 0 ELSE 1 END)
            FROM latest WHERE arena IN ({','.join('?' * len(LLM_ARENAS))}) GROUP BY model, org"""
    groups: dict[tuple[str, str], dict] = {}
    for model, org, prio in con.execute(q, LLM_ARENAS):
        fam = family_of(model)
        g = groups.setdefault((norm(fam), org), {"names": {}, "models": []})
        g["models"].append(model)
        g["names"][fam] = min(prio, g["names"].get(fam, 9))
    return {(min(g["names"], key=lambda n: (g["names"][n], -n.count("-"), n)), org): g["models"]
            for (_, org), g in groups.items()}


def agent_costs(con) -> dict[str, list[dict]]:
    rows = con.execute("""SELECT model, cost_per_task_p50, output_tokens_per_task_p50
        FROM latest WHERE arena='agent' AND variant='aggregate' AND category='overall'
        AND site_default=1 AND cost_per_task_p50 IS NOT NULL ORDER BY cost_per_task_p50""")
    out: dict[str, list[dict]] = {}
    for model, cost, toks in rows:
        out.setdefault(norm(family_of(model)), []).append({
            "model": model, "cost_per_task_p50": round(cost, 4),
            "output_tokens_per_task_p50": round(toks) if toks is not None else None})
    return out


# --- matching ---------------------------------------------------------------

def build_or_index(or_models: list[dict]) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for m in or_models:
        mid = m["id"]
        if ":" in mid or mid.startswith("~"):
            continue  # :batch / :free variants, ~latest aliases
        prefix, slug = mid.split("/", 1)
        name = m.get("name", "").split(": ", 1)[-1]
        for key in {norm(slug), norm(name)}:
            idx.setdefault(f"{prefix}|{key}", m)
    return idx


def build_md_index(md: dict) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for prov, pdata in md.items():
        for mid, m in (pdata.get("models") or {}).items():
            for key in {norm(mid.split("/")[-1]), norm(m.get("name", ""))}:
                idx.setdefault(f"{prov}|{key}", m)
    return idx


def match_or(family: str, org: str, idx: dict[str, dict], by_id: dict[str, dict]):
    if family in OVERRIDES:
        oid = OVERRIDES[family]
        return by_id.get(oid) if oid else None
    for prefix in ORGS.get(org, ([], [], []))[0]:
        hit = idx.get(f"{prefix}|{norm(family)}")
        if hit:
            return hit
    return None


def match_md(family: str, org: str, or_id: str | None, idx: dict[str, dict]):
    keys = [norm(family)]
    if or_id:
        keys.append(norm(or_id.split("/", 1)[1]))
    for prov in ORGS.get(org, ([], [], []))[1]:
        for k in keys:
            if f"{prov}|{k}" in idx:
                return prov, idx[f"{prov}|{k}"]
    return None, None


def per_m(x) -> float | None:
    try:
        return round(float(x) * 1e6, 4)
    except (TypeError, ValueError):
        return None


def blended(i, o):
    return round((3 * i + o) / 4, 4) if i is not None and o is not None else None


# --- main -------------------------------------------------------------------

def build(offline: bool, max_age_h: float, mode: str) -> list[dict]:
    con = sqlite3.connect(DB)
    fams = arena_families(con)
    agents = agent_costs(con)

    or_models = cached_json(RAW / "openrouter_models.json", OR_MODELS_URL, offline, max_age_h)["data"]
    md = cached_json(RAW / "models_dev_api.json", MODELS_DEV_URL, offline, max_age_h)
    or_by_id = {m["id"]: m for m in or_models}
    or_idx, md_idx = build_or_index(or_models), build_md_index(md)

    records = []
    for (family, org), arena_models in sorted(fams.items()):
        orm = match_or(family, org, or_idx, or_by_id)
        md_prov, mdm = match_md(family, org, orm["id"] if orm else None, md_idx)
        if not orm and not mdm:
            continue
        notes = [FAMILY_NOTES[family]] if family in FAMILY_NOTES else []
        eps, eps_mode = endpoint_stats(orm["id"], offline, max_age_h, mode) if orm else (None, None)
        first_party = ORGS.get(org, ([], [], []))[2]

        # price
        inp = out = None
        if mdm and (mdm.get("cost") or {}).get("input") is not None:
            inp, out = mdm["cost"].get("input"), mdm["cost"].get("output")
            source, source_id = "models.dev", f"{md_prov}/{mdm['id']}"
        else:
            fp = [e for e in (eps or []) if e["provider"] in first_party and e["prompt"] is not None]
            if fp:
                inp, out = per_m(fp[0]["prompt"]), per_m(fp[0]["completion"])
                source, source_id = "openrouter", orm["id"]
                notes.append(f"price from first-party OpenRouter endpoint ({fp[0]['provider']})")
            else:
                inp, out = per_m(orm["pricing"].get("prompt")), per_m(orm["pricing"].get("completion"))
                source, source_id = "openrouter", orm["id"]
                notes.append("OpenRouter listed price (may be cheapest third-party host or promo)")
        if inp == 0 and out == 0:
            notes.append("listed as free (free tier); treat as unknown for cost sorting")
        if orm and source == "models.dev":
            oi, oo = per_m(orm["pricing"].get("prompt")), per_m(orm["pricing"].get("completion"))
            if oi is not None and inp and (abs(oi - inp) / inp > 0.2 or abs((oo or 0) - out) / max(out, 1e-9) > 0.2):
                notes.append(f"OpenRouter lists ${oi}/${oo} per M")

        # speed
        tps = weighted(eps or [], "p50_throughput", "throughput_n")
        ttft = weighted(eps or [], "p50_latency_ms", "latency_n")
        if eps:
            fastest = max((e for e in eps if e.get("p50_throughput")), key=lambda e: e["p50_throughput"], default=None)
            if fastest and tps and fastest["p50_throughput"] > 1.5 * tps:
                notes.append(f"fastest host {fastest['provider']} ~{fastest['p50_throughput']} tok/s")
        elif orm:
            notes.append("no OpenRouter speed stats")

        ctx = (mdm or {}).get("limit", {}).get("context") if mdm else None
        ctx = ctx or (orm or {}).get("context_length")
        released = (mdm or {}).get("release_date")
        if not released and orm and orm.get("created"):
            released = datetime.fromtimestamp(orm["created"], timezone.utc).strftime("%Y-%m-%d")

        records.append({
            "family": family,
            "org": org,
            "source": source,
            "source_id": source_id,
            "openrouter_id": orm["id"] if orm else None,
            "input_per_m": inp,
            "output_per_m": out,
            "blended_per_m": blended(inp, out),
            "context_tokens": ctx,
            "tokens_per_sec": round(tps, 1) if tps else None,
            "ttft_s": round(ttft / 1000, 2) if ttft else None,
            "speed_source": SPEED_SOURCE.get(eps_mode) if tps else None,
            "released": released,
            "arena_models": sorted(arena_models),
            "agent_cost_per_task": agents.get(norm(family), []),
            "notes": "; ".join(notes) or None,
        })
    return records


def coverage(records: list[dict]) -> None:
    con = sqlite3.connect(DB)
    by_fam = {norm(r["family"]): r for r in records}
    for arena in ("text", "webdev"):
        models = [m for (m,) in con.execute(
            """SELECT model FROM latest WHERE arena=? AND category='overall' AND site_default=1
               AND rank<=50 ORDER BY rank""", (arena,))]
        fams = list(dict.fromkeys(family_of(m) for m in models))
        get = lambda f: by_fam.get(norm(f))  # noqa: E731
        priced = [f for f in fams if get(f) and get(f)["input_per_m"] is not None]
        sped = [f for f in fams if get(f) and get(f)["tokens_per_sec"]]
        miss = [f for f in fams if not get(f)]
        nospeed = [f for f in fams if get(f) and not get(f)["tokens_per_sec"]]
        print(f"{arena}/overall top 50: {len(fams)} families, {len(priced)} priced, "
              f"{len(sped)} with speed.\n  unmatched: {', '.join(miss) or '-'}"
              + (f"\n  priced, no speed: {', '.join(nospeed) or '-'}" if sped else ""))


def show(records: list[dict], names: list[str]) -> None:
    by_fam = {norm(r["family"]): r for r in records}
    print(f"{'family':24} {'in$/M':>7} {'out$/M':>7} {'blend':>7} {'ctx':>8} {'tok/s':>6} {'ttft':>5}  source")
    for n in names:
        r = by_fam.get(norm(n))
        if not r:
            print(f"{n:24} (no match)")
            continue
        f = lambda v, p=2: "-" if v is None else f"{v:.{p}f}"  # noqa: E731
        ctx = f"{r['context_tokens'] // 1000}K" if r["context_tokens"] else "-"
        print(f"{n:24} {f(r['input_per_m']):>7} {f(r['output_per_m']):>7} {f(r['blended_per_m']):>7} "
              f"{ctx:>8} {f(r['tokens_per_sec'], 0):>6} {f(r['ttft_s']):>5}  {r['source']}:{r['source_id']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use raw/prices cache only")
    ap.add_argument("--max-age", type=float, default=6, help="cache freshness in hours (default 6)")
    ap.add_argument("--show", nargs="*", help="print a table for these families")
    ap.add_argument("--scrape-pages", action="store_true",
                    default=os.environ.get("OPENROUTER_SCRAPE_PAGES") == "1",
                    help="opt-in: read speed from OpenRouter's public model pages when no "
                         "OPENROUTER_API_KEY is set (their ToS prohibit scraping; prefer the key)")
    a = ap.parse_args()
    mode = stats_mode(a.scrape_pages)
    print({"api": "speed: OpenRouter API (OPENROUTER_API_KEY set)",
           "page": "speed: parsing OpenRouter model pages (--scrape-pages)",
           "api-public": "speed: none (set OPENROUTER_API_KEY to include it)"}[mode]
          + (" [offline: using cache]" if a.offline else ""))
    records = build(a.offline, a.max_age, mode)
    # when the price lists were downloaded (the cache may be up to --max-age old)
    fetched_at = datetime.fromtimestamp((RAW / "models_dev_api.json").stat().st_mtime,
                                        timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUT.write_text(json.dumps({"fetched_at": fetched_at, "records": records}, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(records)} families")
    coverage(records)
    if a.show:
        show(records, a.show)


if __name__ == "__main__":
    main()
