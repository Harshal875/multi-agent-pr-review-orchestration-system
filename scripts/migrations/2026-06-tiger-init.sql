-- ============================================================================
-- Tiger Cloud init migration — the memory, time, and truth lanes in one file.
-- Idempotent (safe to re-run). See ARCHITECTURE.md Part II and ROADMAP.md §4.
-- Run in Phase 13 (Infrastructure, pulled forward per ROADMAP §5).
-- ============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vectorscale;
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============ MEMORY LANE ============
CREATE TABLE IF NOT EXISTS code_chunks (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    repo         TEXT         NOT NULL,
    path         TEXT         NOT NULL,
    symbol       TEXT,
    chunk_index  INT          NOT NULL,
    content      TEXT         NOT NULL,
    embedding    VECTOR(256)  NOT NULL,
    token_count  INT,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (repo, path, chunk_index)
);

CREATE INDEX IF NOT EXISTS code_chunks_emb_idx
    ON code_chunks USING diskann (embedding vector_cosine_ops);

ALTER TABLE code_chunks
    ADD COLUMN IF NOT EXISTS content_tsv TSVECTOR
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

CREATE INDEX IF NOT EXISTS code_chunks_fts_idx
    ON code_chunks USING GIN (content_tsv);

CREATE TABLE IF NOT EXISTS repo_file_index (
    repo            TEXT NOT NULL,
    path            TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    last_indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (repo, path)
);

-- ============ TIME LANE ============
CREATE TABLE IF NOT EXISTS agent_events (
    ts            TIMESTAMPTZ  NOT NULL,
    review_id     UUID         NOT NULL,
    agent         TEXT         NOT NULL,
    span_id       UUID         NOT NULL DEFAULT gen_random_uuid(),
    parent_span   UUID,
    event_type    TEXT         NOT NULL,
    model         TEXT,
    tokens_in     INT,
    tokens_out    INT,
    cost_usd      NUMERIC(10,6),
    latency_ms    INT,
    outcome       TEXT,
    confidence    NUMERIC(4,3),
    payload       JSONB
);

SELECT create_hypertable('agent_events', by_range('ts', INTERVAL '1 day'),
    if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS agent_health_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', ts) AS bucket,
    agent,
    count(*) FILTER (WHERE event_type = 'llm.call') AS llm_calls,
    sum(cost_usd) AS cost_usd,
    approx_percentile(0.95, percentile_agg(latency_ms)) AS p95_ms,
    count(*) FILTER (WHERE outcome = 'rejected')::float
        / NULLIF(count(*) FILTER (WHERE outcome IS NOT NULL), 0) AS rejection_rate
FROM agent_events
GROUP BY bucket, agent
WITH NO DATA;

SELECT add_continuous_aggregate_policy('agent_health_1m',
    start_offset => INTERVAL '2 hours', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS pr_cost_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    review_id,
    sum(cost_usd) AS total_cost_usd,
    count(DISTINCT agent) AS agents_used,
    max(confidence) AS max_confidence
FROM agent_events
GROUP BY bucket, review_id
WITH NO DATA;

-- ============ TRUTH LANE ============
CREATE TABLE IF NOT EXISTS pr_review_records (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo             TEXT NOT NULL,
    pr_number        INT NOT NULL,
    commit_sha       TEXT NOT NULL,
    delivery_id      TEXT UNIQUE NOT NULL,   -- GitHub X-GitHub-Delivery, idempotency key
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending|posted|awaiting_human|rejected
    overall_confidence NUMERIC(4,3),
    github_review_id TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    posted_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS finding_records (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id    UUID NOT NULL REFERENCES pr_review_records(id),
    agent_type   TEXT NOT NULL,   -- security|quality|tests|docs
    severity     TEXT NOT NULL,   -- CRITICAL|HIGH|MEDIUM|LOW|INFO
    category     TEXT NOT NULL,
    summary      TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    line_start   INT,
    line_end     INT,
    suggestion   TEXT,
    confidence   NUMERIC(4,3) NOT NULL,
    rationale    TEXT NOT NULL,
    duplicate_of UUID REFERENCES finding_records(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hitl_reviews (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id    UUID NOT NULL REFERENCES pr_review_records(id),
    reason       TEXT NOT NULL,   -- low_confidence|critical_finding
    status       TEXT NOT NULL DEFAULT 'open',  -- open|approved|rejected|edited
    reviewer     TEXT,
    resolved_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hitl_feedback (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id   UUID NOT NULL REFERENCES finding_records(id),
    verdict      TEXT NOT NULL,  -- confirmed|disputed|dismissed
    comment      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
