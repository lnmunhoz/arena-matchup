# Model routing table

Generated 2026-11-26 by Arena Matchup from 6 picked model and effort pairs.
- Style control: on (ratings discount answer length and formatting)
- Arena snapshots: text 2026-11-22, webdev 2026-11-23, vision 2026-11-25, search 2026-11-19, document 2026-11-09, text_to_image 2026-11-20, image_edit 2026-11-17, text_to_video 2026-11-09, image_to_video 2026-11-09, video_edit 2026-11-10, agent 2026-11-22
- Prices fetched: 2026-11-26 15:02 UTC. This build has no speed data.
- Sources: [arena.ai](https://arena.ai/leaderboard), [LMArena dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset) (CC BY 4.0), [models.dev](https://models.dev), [OpenRouter](https://openrouter.ai/models)
- View this selection: open `index.html` from https://github.com/lnmunhoz/arena-matchup with the hash `#e-dg85i-zf008-b7q62-fnp2m-kwow4-z7ptt`

## Routing

| Job | Use (model · effort) | Confidence | Also tied | Best value pick | Why |
| --- | --- | --- | --- | --- | --- |
| General chat | Gemini 4 Neon · High | Toss-up | Claude Opus 5.5 · High | – | top rating, 5 pts ahead of the tied pick |
| Coding | Gemini 4 Neon · High | Toss-up | Claude Opus 5.5 · High | – | top rating, 11 pts ahead of the tied pick |
| Web/app building | Claude Opus 5.5 · Max | Clear winner | – | – | leads the next pick by 48 pts |
| Hard reasoning | Gemini 4 Neon · High | Toss-up | Claude Opus 5.5 · High | – | top rating, 11 pts ahead of the tied pick |
| Math | Gemini 4 Neon · High | Toss-up | Claude Opus 5.5 · High, Claude Sonnet 5.5 · xHigh, GPT-5.6 Sol · xHigh | Claude Sonnet 5.5 · xHigh | top rating, 12 pts ahead of the closest of 3 tied picks; best value is tied with the winner and 33% cheaper ($4 vs $6 per M) |
| Writing | Claude Opus 5.5 · High | Toss-up | Gemini 4 Neon · High | Gemini 4 Neon · High | top rating, 14 pts ahead of the tied pick; best value is tied with the winner and 25% cheaper ($6 vs $8 per M) |
| Long documents | Gemini 4 Neon · High | Toss-up | Claude Opus 5.5 · High | – | top rating, 1 pt ahead of the tied pick |
| Instruction following | Gemini 4 Neon · High | Toss-up | Claude Opus 5.5 · High | – | top rating, 1 pt ahead of the tied pick |
| Multi-turn | Gemini 4 Neon · High | Toss-up | Claude Opus 5.5 · High, GPT-5.6 Sol · xHigh | – | top rating, 16 pts ahead of the closest of 2 tied picks |
| Vision | Claude Opus 5.5 · High | Toss-up | GPT-5.6 Sol · xHigh | – | top rating, 5 pts ahead of the tied pick |
| Search | GPT-5.6 Sol · xHigh | Only one tested | – | – | only pick ranked on this board |
| Documents | GPT-5.6 Sol · xHigh | Only one tested | – | – | only pick ranked on this board |
| Agentic work | Claude Opus 5.5 · Max | Toss-up | Gemini 4 Neon · High | Gemini 4 Neon · High | top rating, 0.008 ahead of the tied pick; best value is tied with the winner and 2.3× cheaper ($2.48 vs $5.79 per agent task) |

## Models

| Model | Effort | Vendor | API ids | $ in / out per M | Blended $/M | Context | Agent task cost | Best for | Tied for best | Weak at | Not tested |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5 | Max | Anthropic | models.dev `anthropic/claude-opus-5-5`, OpenRouter `anthropic/claude-opus-5.5` | $4 / $20 | $8 | 1M | $5.79 | Web/app building | Agentic work | – | General chat, Coding, Hard reasoning, Math, Writing, Long documents, Instruction following, Multi-turn, Vision, Search, Documents |
| Gemini 4 Neon | High | Google | models.dev `google/gemini-4-neon`, OpenRouter `google/gemini-4-neon` | $3 / $15 | $6 | 1M | $2.48 | – | General chat, Coding, Hard reasoning, Math, Writing, Long documents, Instruction following, Multi-turn, Agentic work | – | Web/app building, Vision, Search, Documents |
| Claude Opus 5.5 | High | Anthropic | models.dev `anthropic/claude-opus-5-5`, OpenRouter `anthropic/claude-opus-5.5` | $4 / $20 | $8 | 1M | $1.93 | – | General chat, Coding, Hard reasoning, Math, Writing, Long documents, Instruction following, Multi-turn, Vision | Agentic work | Web/app building, Search, Documents |
| GPT-5.6 Sol | xHigh | OpenAI | models.dev `openai/gpt-5.6-sol`, OpenRouter `openai/gpt-5.6-sol` | $4 / $20 | $8 | 1M | $1.31 | Search (only one tested), Documents (only one tested) | Math, Multi-turn, Vision | General chat, Coding, Web/app building, Hard reasoning, Writing, Long documents, Instruction following, Agentic work | – |
| Claude Sonnet 5.5 | xHigh | Anthropic | models.dev `anthropic/claude-sonnet-5-5`, OpenRouter `anthropic/claude-sonnet-5.5` | $2 / $10 | $4 | 1M | – | – | Math | General chat, Coding, Web/app building, Hard reasoning, Writing, Long documents, Instruction following, Multi-turn, Vision | Search, Documents, Agentic work |
| Claude Sonnet 5.5 | High | Anthropic | models.dev `anthropic/claude-sonnet-5-5`, OpenRouter `anthropic/claude-sonnet-5.5` | $2 / $10 | $4 | 1M | $0.75 | – | – | Web/app building, Agentic work | General chat, Coding, Hard reasoning, Math, Writing, Long documents, Instruction following, Multi-turn, Vision, Search, Documents |

## Ranks

Rank on each job's leaderboard (rating). "–" means not tested.

| Job (leaderboard) | Claude Opus 5.5 · Max | Gemini 4 Neon · High | Claude Opus 5.5 · High | GPT-5.6 Sol · xHigh | Claude Sonnet 5.5 · xHigh | Claude Sonnet 5.5 · High |
| --- | --- | --- | --- | --- | --- | --- |
| General chat (text/overall, 427 ranked) | – | #3 (1512) | #5 (1507) | #25 (1485) | #49 (1473) | – |
| Coding (text/coding, 422 ranked) | – | #2 (1558) | #9 (1547) | #22 (1533) | #50 (1516) | – |
| Web/app building (webdev/overall, 162 ranked) | #2 (1820) | – | – | #39 (1616) | #3 (1773) | #13 (1715) |
| Hard reasoning (text/hard_prompts, 427 ranked) | – | #3 (1541) | #5 (1530) | #22 (1511) | #47 (1496) | – |
| Math (text/math, 410 ranked) | – | #3 (1530) | #6 (1519) | #28 (1494) | #26 (1498) | – |
| Writing (text/creative_writing, 425 ranked) | – | #5 (1504) | #3 (1518) | #23 (1471) | #32 (1461) | – |
| Long documents (text/longer_query, 405 ranked) | – | #4 (1522) | #6 (1521) | #23 (1498) | #36 (1487) | – |
| Instruction following (text/instruction_following, 427 ranked) | – | #3 (1517) | #4 (1517) | #18 (1490) | #30 (1477) | – |
| Multi-turn (text/multi_turn, 425 ranked) | – | #4 (1519) | #11 (1503) | #24 (1491) | #67 (1470) | – |
| Vision (vision/overall, 170 ranked) | – | – | #11 (1292) | #17 (1288) | #44 (1264) | – |
| Search (search/overall, 45 ranked) | – | – | – | #1 (1254) | – | – |
| Documents (document/overall, 46 ranked) | – | – | – | #7 (1487) | – | – |
| Agentic work (agent/overall, 69 ranked) | #2 (0.191) | #3 (0.183) | #8 (0.139) | #25 (0.035) | – | #17 (0.079) |

## Arena names

The exact LMArena model names behind each entry, to trace a row back to the leaderboard.

- Claude Opus 5.5 · Max: `Claude Opus 5.5 (Max)`
- Gemini 4 Neon · High: `Gemini 4 Neon (High)`
- Claude Opus 5.5 · High: `Claude Opus 5.5 (High)`
- GPT-5.6 Sol · xHigh: `GPT-5.6 Sol (xHigh)`, `GPT-5.6 Sol (xHigh, Codex Harness)`
- Claude Sonnet 5.5 · xHigh: `Claude Sonnet 5.5 (xHigh)`
- Claude Sonnet 5.5 · High: `Claude Sonnet 5.5 (High)`

## How to read this

- Ratings come from blind human-preference votes on LMArena. Ranks, Best for and Weak at compare these picks with each other, not with the whole leaderboard.
- A tie means the confidence intervals overlap, so more votes could flip the order. Treat tied picks as equal and choose on price or speed.
- Best value is the cheapest pick that is tied with the winner or within 15 rating points. On Agentic work it compares Arena's measured cost per agent task. Every other job compares blended price per token.
- Every effort level of a model has the same price per token. Higher effort writes more output tokens, so the agent task cost rises with effort.
- Prices are list prices in US dollars per million tokens, before caching or batch discounts. Blended assumes 3 input tokens per output token.
