# Arena Matchup

Arena Matchup is a single HTML page for picking an LLM. Choose a few models and it shows which one wins each job, such as coding, writing, web app building or agentic work, and what each one costs. It combines all 11 leaderboards from [LMArena](https://arena.ai) (now arena.ai) with list prices from [models.dev](https://models.dev) and OpenRouter.

![Arena Matchup comparing six model and effort pairs, such as Claude Opus 5.5 at High and at Max, in a cheat sheet and a price table](docs/screenshot.png)

Each effort level counts as its own model. Claude Opus 5.5 at High and Claude Opus 5.5 at Max are two picks, and every part of the page names the effort level next to the model.

The page has four parts:

- A cheat sheet lists what each pick is best at, tied on, or behind on, compared only with your other picks.
- A job board shows, for each job, the winner and how many rating points behind it every other pick is.
- A price table puts blended price per million tokens next to the rating on the job you choose, one row per pick. It marks the cheapest row that is tied with the winner or within 15 points of it. On the Agentic work job it compares Arena's measured cost per agent task instead.
- A rank matrix shows your picks' rank on every leaderboard and category.

## Quick start

Open `index.html` in a browser. It is one self-contained file with the data embedded, so it needs no server or build step.

To pull fresh data and rebuild it:

```sh
./refresh.sh
```

`refresh.sh` needs [uv](https://docs.astral.sh/uv/) and `python3`. The scripts use only the Python standard library, plus `pyarrow`, which uv installs on the fly to read the Hugging Face parquet files. Prices are cached for 6 hours in `raw/prices/`. If the price fetch fails, the build falls back to that cache, then to the committed `data/prices.json`.

### Speed data

Speed (output tokens per second and time to first token) comes from OpenRouter and is optional. The committed page has none. To include it, set an OpenRouter API key before refreshing:

```sh
OPENROUTER_API_KEY=sk-or-... ./refresh.sh
```

With the key, `scripts/fetch_prices.py` reads per-provider stats from OpenRouter's official endpoints API (`/api/v1/models/<id>/endpoints`). Without a key, that API returns the stats as null and the page hides every speed column and filter.

`--scrape-pages` (or `OPENROUTER_SCRAPE_PAGES=1`) is an opt-in fallback. It reads the same stats from OpenRouter's public model pages. [OpenRouter's terms](https://openrouter.ai/terms) prohibit scraping the site in section 7, so this flag is off by default. Use the API key instead.

## Hand off to an agent

**Export for agents** in the selection bar turns your picks into a routing table that an AI agent or a task router can read. It opens a dialog with two formats:

- **Markdown** has a routing table with one row per job: the model and effort level to use, whether the win is clear or a toss-up, which picks tie with it and the best value pick. Below it are a models table with API ids, prices, agent task cost and what each pick is best at, a rank table, and the exact Arena model names.
- **JSON** holds the same data as structured fields, with `null` where a value is unknown. Each model has a lowercase `effort` value such as `high`, `xhigh` or `max`, plus a display label.

Copy the text or download it as `arena-routing-YYYY-MM-DD.md` or `.json`. The export follows the current picks, the style control setting and "Combine effort levels". See [docs/example-routing.md](docs/example-routing.md) and [docs/example-routing.json](docs/example-routing.json) for a sample.

To get the same output without a browser, pass the hash from the page URL to `scripts/export.py`:

```sh
python3 -I scripts/export.py --hash '#e-dg85i-zf008-b7q62-fnp2m-kwow4-z7ptt' --format md
```

The script runs the page's own code under Node, so it needs `node` on your PATH.

## Data sources

| Data | Source | License or terms |
| --- | --- | --- |
| Ranks, ratings, confidence intervals, vote counts, agent cost per task | [`lmarena-ai/leaderboard-dataset`](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset) on Hugging Face, published by [LMArena](https://arena.ai) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| List prices, context windows, release dates | [models.dev](https://models.dev) ([repo](https://github.com/anomalyco/models.dev)) | MIT |
| Prices for models missing from models.dev, optional speed | [OpenRouter API](https://openrouter.ai/docs) | [OpenRouter terms](https://openrouter.ai/terms) |

The leaderboard data in `index.html` comes from LMArena under CC BY 4.0. This project changes it. It merges the setup and date variants of each model and effort level, and it joins prices. LMArena does not endorse this project.

### Limits

- **Style control is on by default.** For the text, vision, search and document arenas, the page shows LMArena's style-controlled ratings, which discount answer length and formatting. The toggle switches to the raw ratings.
- **Each effort level is its own model.** "Claude Opus 5.5 (High)" and "Claude Opus 5.5 (Max)" are separate picks, each with its own ranks, ratings and agent task cost. Thinking modes and thinking budgets count as effort levels, so "Kimi K2.5 (Thinking)" and "Kimi K2.5 (Instant)" are separate picks too. A model that Arena lists with no effort level gets no tag, or "Default" when the same model also has named levels.
- **Setups and date stamps don't split a pick.** "GPT-5.6 Sol (xHigh, Codex Harness)" and "GPT-5.6 Sol (xHigh)" are one pick, so its cells fill across arenas. The page adds "via Codex Harness" where it uses that setup's rating. An effort level that Arena hasn't rated on a leaderboard shows as "not tested" there.
- **"Combine effort levels" is off by default.** Turned on, it merges the effort levels of each model again and uses whichever level ranks best on each leaderboard.
- **Price per token is the same for every effort level of a model.** Higher levels write more tokens, so each task costs more. On the Agentic work job the price table, its chart and the best value notes compare Arena's measured cost per agent task, which differs by effort level.
- **A tie means the confidence intervals overlap.** A pick is tied with the leader when its upper bound reaches the leader's lower bound. More votes could flip the order.
- **Prices are list prices.** They are US dollars per million tokens before discounts, caching or batch pricing. Blended price is 3 parts input to 1 part output. A † marks OpenRouter's top-level price, which can come from a cheaper third-party host than the model maker.
- **Speed is a 30-minute snapshot.** OpenRouter reports medians over the last 30 minutes, averaged across hosts. Numbers move with load.
- **Name matching is conservative.** A model gets a price only when its name matches exactly or through a hand-checked override in `scripts/fetch_prices.py`. In the committed snapshot, 3 of the 44 model families in the text top 50 have no price.

## Files

```
index.html                 the page; open it directly
refresh.sh                 fetch data, then rebuild index.html
scripts/
  fetch_arena.py           Hugging Face dataset to data/arena.sqlite and data/arena_latest.csv
  fetch_prices.py          models.dev and OpenRouter to data/prices.json
  build_page.py            SQLite and prices.json to index.html (--fragment for body-only HTML)
  page_template.html       page markup, styles and script; build_page.py fills in the data
  export.py                print the agent routing table for a page hash (runs the page script in Node)
data/prices.json           price snapshot, committed so the page builds offline
docs/                      README screenshots and sample routing exports
```

`data/arena.sqlite`, `data/*.csv` and `raw/` are generated and not committed. `fetch_arena.py --backfill` loads the full rating history into the SQLite database.

## License

The code is MIT, see [LICENSE](LICENSE). The data keeps its sources' licenses, listed above.
