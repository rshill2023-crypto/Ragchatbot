# PRD — Groww Mutual Fund FAQ Assistant (RAG Demo)

## 1. Overview

Build a small, facts-only FAQ assistant for mutual fund schemes listed on Groww. The assistant answers factual questions (expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, statement downloads) using **only official public Groww pages**, and cites one source link in every answer.

This is a **RAG demonstration**, so every pipeline stage (loading, chunking, embedding, retrieval, generation) must persist observable artifacts that can be shown/inspected.

## 2. Problem Statement

Retail users comparing mutual fund schemes and support/content teams repeatedly ask the same factual questions. Generic chatbots either hallucinate, give advice, or cite unreliable sources. We need a transparent, source-backed assistant that only answers factual queries and safely refuses opinionated/portfolio questions.

## 3. Goals

- Answer factual MF questions accurately from a small, fixed corpus.
- Attach exactly one clear citation link to every answer.
- Refuse investment advice / opinionated queries politely with an educational link.
- Expose every RAG stage's intermediate data for demo purposes.
- Keep all components (models, DB, LLM) configurable.

## 4. Non-Goals

- No investment advice, recommendations, or buy/sell guidance.
- No return computation, comparison, or performance claims.
- No PII collection or storage (PAN, Aadhaar, account numbers, OTPs, emails, phone numbers).
- No scraping of links internal to the 5 source pages.
- No third-party blogs or unofficial sources.
- No multi-AMC coverage beyond the scope below.

## 5. Target Users

| User | Need |
|------|------|
| Retail MF investors | Quick factual answers with a trustworthy source |
| Support / content teams | Faster handling of repetitive MF questions |

## 6. Scope — Source Corpus

Scrape and store **only these 5 pages** (no internal link crawling):

| # | Scheme / Page | URL |
|---|---------------|-----|
| 1 | AMC overview — HDFC Mutual Fund | https://groww.in/mutual-funds/amc/hdfc-mutual-funds |
| 2 | Large Cap — HDFC Large Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 3 | Flexi Cap — HDFC Flexi Cap Direct Plan Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 4 | ELSS — HDFC ELSS Tax Saver Fund Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | Mid Cap — HDFC Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |

If a query cannot be answered from these pages (e.g., an official factsheet reference), respond with the closest relevant official link and state the limitation.

## 7. Functional Requirements

### 7.1 RAG Pipeline (phase-wise, explicit artifacts)

Each stage must write its output to disk (e.g., `data/artifacts/`) so the demo can show it.

#### Phase 1 — Data Loading
- Fetch the 5 configured URLs.
- Store raw HTML and cleaned text per page, with metadata: `source_url`, `page_title`, `scheme`, `category`, `fetched_at`.
- No crawling of internal links.

#### Phase 2 — Data Chunking
- Chunking strategy is **data-driven** (AI chunking agent may select it based on page structure), but must be deterministic and configurable.
- Default: section-aware/heading-based chunking with token overlap.
- Persist chunks with metadata (`chunk_id`, `source_url`, `section`, `char_count`, `token_count`) and a manifest describing the chosen strategy and rationale.

#### Phase 3 — Data Embedding
- Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (configurable).
- Store embeddings alongside chunk IDs and metadata.
- Persist embedding run metadata (model name, dimension, timestamp, chunk count).

#### Phase 4 — Vector Store
- Vector DB: **ChromaDB** (configurable).
- Persist collection name, embedding model, and chunk mapping.
- Provide a reproducible rebuild path from artifacts.

#### Phase 5 — Retrieval
- Use the **same** embedding model and vector DB as ingestion.
- Return top-k chunks with similarity scores and source metadata.
- Persist retrieval trace per query (query, top-k, scores, selected chunks).

#### Phase 6 — Generation / Answering
- LLM via **Groq** using API key and model from `.env` (default `qwen/qwen3.8-27b`).
- Provider must be abstracted for configurable alternatives: Gemini, OpenAI, Anthropic, Mistral.
- Prompt enforces: facts-only, ≤3 sentences, exactly one citation link, no advice, include `Last updated from sources: <date>`.
- Persist final prompt + response trace per query.

### 7.2 FAQ Assistant Behavior

**Answer:** factual queries such as:
- "Expense ratio of HDFC Flexi Cap?"
- "ELSS lock-in period?"
- "Minimum SIP amount?"
- "Exit load?"
- "Riskometer / benchmark?"
- "How to download capital-gains statement?"

**Refuse:** opinionated/portfolio queries (e.g., "Should I buy/sell?", "Which fund is better?", "Will this give good returns?") with a polite, facts-only message plus a relevant educational/official link.

**Output format (every answer):**
- ≤3 sentences of factual content
- Exactly one source link
- `Last updated from sources: <date>`
- No performance claims / return comparisons

### 7.3 UI

Minimal UI with:
- Welcome line
- 3 example questions
- Input box + send
- Rendered answer with citation
- Disclaimer: **"Facts-only. No investment advice."**

Streamlit (or equivalent lightweight framework) acceptable for the prototype.

## 8. Configuration

All of the following must live in a config file (e.g., `config.yaml`), overridable via env:

```yaml
ingestion:
  urls: [ ...5 URLs... ]
  artifacts_dir: data/artifacts
chunking:
  strategy: auto        # auto | heading | fixed
  chunk_size: 512
  chunk_overlap: 64
embedding:
  model: sentence-transformers/all-MiniLM-L6-v2
vector_db:
  provider: chromadb
  collection: groww_mf_faq
  persist_dir: data/chroma
retrieval:
  top_k: 5
llm:
  provider: groq        # groq | gemini | openai | anthropic | mistral
  model: qwen/qwen3.8-27b
  temperature: 0.1
  max_sentences: 3
```

Secrets (`GROQ_API_KEY`, etc.) go in `.env`, never committed.

## 9. Constraints & Guardrails

- **Public sources only** — official Groww/AMC/SEBI/AMFI pages; no third-party blogs.
- **No PII** — reject/never store PAN, Aadhaar, account numbers, OTPs, emails, phone numbers.
- **No performance claims** — link to official factsheet instead.
- **Clarity & transparency** — ≤3 sentences, one citation, `Last updated from sources:` line.
- **Politeness** — safe, non-judgmental refusals for advice-seeking queries.

## 10. Non-Functional Requirements

- Reproducible ingestion (`make ingest` / single command).
- Observable artifacts for every pipeline stage.
- Config-driven swap of embedding model, vector DB, and LLM without code changes.
- Response latency acceptable for demo (< ~5s typical on Groq).
- No secrets in repo; `.env.example` provided.

## 11. Deliverables

1. Working prototype (app link) **or** ≤3-min demo video.
2. Source list (`sources.md` / `sources.csv`) of the 15–25 URLs used.
3. `README.md` with setup steps, scope (AMC + schemes), and known limits.
4. Sample Q&A file (5–10 queries with answers + links).
5. Disclaimer snippet used in the UI.
6. Persisted pipeline artifacts demonstrating each RAG stage.

## 12. Acceptance Criteria

- [ ] All 5 pages ingested without following internal links.
- [ ] Chunking strategy documented with rationale and artifacts.
- [ ] Embeddings + ChromaDB collection reproducible from config.
- [ ] Factual queries return correct facts with exactly one source link.
- [ ] Advice-seeking queries are refused politely with an educational link.
- [ ] Answers are ≤3 sentences and include `Last updated from sources:`.
- [ ] No PII accepted/stored; no performance claims made.
- [ ] Models/DB/LLM swappable via config.
- [ ] Each RAG stage's data is explicitly stored and inspectable.

## 13. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Groww page structure changes | Store raw HTML + cleaned text; version artifacts |
| Scraping blocks / rate limits | Polite rate limiting, retries, cached snapshots |
| LLM hallucination | Strict prompt + retrieval grounding + citation enforcement |
| Misclassified advice query | Explicit intent router + refusal template + tests |
| Stale data | Store `fetched_at` and show `Last updated from sources:` |

## 14. Open Questions

- Should the corpus include Groww help pages for "download statement" if not present on the 5 pages?
- Preferred UI framework (Streamlit vs. lightweight web app)?
- Hosting target for the prototype link?
- Refresh cadence for re-ingestion?
