-- V005: Sorvia platform schema.
--   app_user              platform accounts (role + branch scope)
--   scope_ticket          one-time capability tickets (see V006)
--   session_scope         per-transaction security context of the reader role
--   schema_doc            semantic layer with vector embeddings for retrieval
--   nl_query              every natural-language question and its outcome
--   query_feedback        human correctness labels (ground truth for evaluation)
--   index_recommendation  output of the self-tuning index advisor

SET search_path = sorvia, public;

CREATE TYPE sorvia.user_role AS ENUM ('admin', 'manager', 'pharmacist');
CREATE TYPE sorvia.query_status AS ENUM ('ok', 'blocked', 'error', 'timeout');
CREATE TYPE sorvia.recommendation_status AS ENUM ('proposed', 'applied', 'rejected');

CREATE TABLE sorvia.app_user (
    user_id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      text    NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_.]{3,40}$'),
    password_hash text    NOT NULL,
    display_name  text    NOT NULL,
    role          sorvia.user_role NOT NULL,
    branch_id     smallint REFERENCES pharma.branch,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    -- Pharmacists are always bound to exactly one branch.
    CHECK (role <> 'pharmacist' OR branch_id IS NOT NULL)
);

CREATE TRIGGER audit_app_user AFTER INSERT OR UPDATE OR DELETE ON sorvia.app_user
    FOR EACH ROW EXECUTE FUNCTION audit.log_change('password_hash');

CREATE TABLE sorvia.scope_ticket (
    ticket       uuid     PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      integer  NOT NULL REFERENCES sorvia.app_user,
    branch_id    smallint REFERENCES pharma.branch,
    all_branches boolean  NOT NULL,
    expires_at   timestamptz NOT NULL DEFAULT clock_timestamp() + interval '30 seconds',
    CHECK (all_branches OR branch_id IS NOT NULL)
);

-- UNLOGGED: purely transient, no WAL cost.
CREATE UNLOGGED TABLE sorvia.session_scope (
    backend_pid  integer  PRIMARY KEY,
    xact_id      xid8     NOT NULL,
    user_id      integer  NOT NULL,
    branch_id    smallint,
    all_branches boolean  NOT NULL
);

CREATE TABLE sorvia.schema_doc (
    doc_id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    object_type     text    NOT NULL CHECK (object_type IN ('table', 'view')),
    schema_name     text    NOT NULL,
    object_name     text    NOT NULL,
    content         text    NOT NULL,
    ddl_summary     text    NOT NULL,
    related_objects text[]  NOT NULL DEFAULT '{}',
    embedding       vector  NOT NULL,
    embedding_model text    NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (schema_name, object_name)
);

CREATE TABLE sorvia.nl_query (
    query_id        bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         integer NOT NULL REFERENCES sorvia.app_user,
    question        text    NOT NULL CHECK (length(question) BETWEEN 1 AND 2000),
    generated_sql   text,
    executed_sql    text,
    status          sorvia.query_status NOT NULL,
    block_reason    text,
    error_message   text,
    provider        text    NOT NULL,
    model           text,
    strategy        text    NOT NULL,
    retrieved_objects text[] NOT NULL DEFAULT '{}',
    repair_attempts smallint NOT NULL DEFAULT 0,
    estimated_cost  double precision,
    row_count       integer,
    llm_ms          integer,
    db_ms           integer,
    total_ms        integer,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX nl_query_user_time_idx   ON sorvia.nl_query (user_id, created_at DESC);
CREATE INDEX nl_query_status_time_idx ON sorvia.nl_query (status, created_at DESC);

CREATE TABLE sorvia.query_feedback (
    query_id   bigint  NOT NULL REFERENCES sorvia.nl_query ON DELETE CASCADE,
    user_id    integer NOT NULL REFERENCES sorvia.app_user,
    is_correct boolean NOT NULL,
    comment    text    CHECK (length(comment) <= 1000),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (query_id, user_id)
);

CREATE TABLE sorvia.index_recommendation (
    recommendation_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name        text    NOT NULL,
    columns           text[]  NOT NULL,
    index_ddl         text    NOT NULL,
    workload_size     integer NOT NULL,
    cost_before       double precision NOT NULL,
    cost_after        double precision NOT NULL,
    improvement_pct   double precision NOT NULL,
    status            sorvia.recommendation_status NOT NULL DEFAULT 'proposed',
    created_at        timestamptz NOT NULL DEFAULT now(),
    decided_at        timestamptz,
    decided_by        integer REFERENCES sorvia.app_user
);

CREATE UNIQUE INDEX index_recommendation_open_uq
    ON sorvia.index_recommendation (index_ddl) WHERE status = 'proposed';
