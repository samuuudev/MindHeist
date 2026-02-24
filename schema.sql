-- ============================================================
-- DISCORD COMPETITIVE BOT — DATABASE SCHEMA (multi-guild)
-- Compatible con PostgreSQL (Pterodactyl container DB)
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. USUARIOS
-- ============================================================
CREATE TABLE users (
    user_id         BIGINT NOT NULL,          -- Discord user ID
    guild_id        BIGINT NOT NULL,          -- Discord guild ID
    username        VARCHAR(64) NOT NULL,
    points          INTEGER NOT NULL DEFAULT 0,
    money           INTEGER NOT NULL DEFAULT 0,
    elo             INTEGER NOT NULL DEFAULT 1000,
    daily_streak    INTEGER NOT NULL DEFAULT 0,
    last_daily      TIMESTAMP,
    gold_wins       INTEGER NOT NULL DEFAULT 0,
    total_quizzes   INTEGER NOT NULL DEFAULT 0,
    correct_answers INTEGER NOT NULL DEFAULT 0,
    robberies_today INTEGER NOT NULL DEFAULT 0,
    last_robbery    TIMESTAMP,
    shield_until    TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY(user_id, guild_id)
);

CREATE INDEX idx_users_points ON users (guild_id, points DESC);
CREATE INDEX idx_users_elo ON users (guild_id, elo DESC);
CREATE INDEX idx_users_gold_wins ON users (guild_id, gold_wins DESC);

-- ============================================================
-- 2. PREGUNTAS
-- ============================================================
CREATE TYPE question_source AS ENUM ('openai', 'opentdb', 'manual');
CREATE TYPE question_difficulty AS ENUM ('easy', 'medium', 'hard');
CREATE TYPE question_category AS ENUM (
    'general', 'science', 'history', 'geography',
    'entertainment', 'sports', 'logic', 'riddle', 'server'
);

CREATE TABLE questions (
    question_id     SERIAL PRIMARY KEY,
    content         TEXT NOT NULL,
    options         JSONB NOT NULL,
    correct_index   SMALLINT NOT NULL,
    difficulty      question_difficulty NOT NULL DEFAULT 'medium',
    category        question_category NOT NULL DEFAULT 'general',
    source          question_source NOT NULL DEFAULT 'openai',
    times_used      INTEGER NOT NULL DEFAULT 0,
    times_correct   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_questions_difficulty ON questions (difficulty);
CREATE INDEX idx_questions_category ON questions (category);

-- ============================================================
-- 3. HISTORIAL DE RESPUESTAS
-- ============================================================
CREATE TABLE answer_history (
    answer_id       SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    guild_id        BIGINT NOT NULL,
    question_id     INTEGER NOT NULL REFERENCES questions(question_id),
    answered_index  SMALLINT NOT NULL,
    is_correct      BOOLEAN NOT NULL,
    points_earned   INTEGER NOT NULL DEFAULT 0,
    money_earned    INTEGER NOT NULL DEFAULT 0,
    context         VARCHAR(20) NOT NULL,
    response_time   REAL,
    answered_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT answer_history_user_fk
        FOREIGN KEY(user_id, guild_id) REFERENCES users(user_id, guild_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_answers_user ON answer_history (user_id, guild_id, answered_at DESC);
CREATE INDEX idx_answers_context ON answer_history (context, answered_at DESC);

-- ============================================================
-- 4. GOLD EVENTS
-- ============================================================
CREATE TABLE gold_events (
    event_id        SERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    question_id     INTEGER REFERENCES questions(question_id),
    reward_points   INTEGER NOT NULL DEFAULT 30,
    jackpot         INTEGER NOT NULL DEFAULT 0,
    winner_id       BIGINT,
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    started_at      TIMESTAMP,
    ended_at        TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT gold_winner_fk FOREIGN KEY(winner_id, guild_id)
        REFERENCES users(user_id, guild_id)
        ON DELETE SET NULL
);

CREATE INDEX idx_gold_active ON gold_events (guild_id, is_active);

-- ============================================================
-- 5. ROBOS PvP
-- ============================================================
CREATE TABLE robberies (
    robbery_id      SERIAL PRIMARY KEY,
    attacker_id     BIGINT NOT NULL,
    victim_id       BIGINT NOT NULL,
    guild_id        BIGINT NOT NULL,
    question_id     INTEGER REFERENCES questions(question_id),
    success         BOOLEAN NOT NULL,
    money_stolen    INTEGER NOT NULL DEFAULT 0,
    points_change   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT robberies_attacker_fk
        FOREIGN KEY(attacker_id, guild_id) REFERENCES users(user_id, guild_id)
        ON DELETE CASCADE,
    CONSTRAINT robberies_victim_fk
        FOREIGN KEY(victim_id, guild_id) REFERENCES users(user_id, guild_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_robberies_attacker ON robberies (attacker_id, guild_id, created_at DESC);
CREATE INDEX idx_robberies_victim ON robberies (victim_id, guild_id, created_at DESC);

-- ============================================================
-- 6. ROLES TEMPORALES
-- ============================================================
CREATE TABLE temp_roles (
    temp_role_id    SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    guild_id        BIGINT NOT NULL,
    role_id         BIGINT NOT NULL,
    role_type       VARCHAR(30) NOT NULL,
    multiplier      REAL DEFAULT 1.0,
    granted_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMP NOT NULL,
    removed         BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT temp_roles_user_fk
        FOREIGN KEY(user_id, guild_id) REFERENCES users(user_id, guild_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_temp_roles_active ON temp_roles (guild_id, removed, expires_at);
CREATE INDEX idx_temp_roles_user ON temp_roles (user_id, guild_id, removed);

-- ============================================================
-- 7. EVENTOS ESPECIALES
-- ============================================================
CREATE TYPE event_type AS ENUM (
    'double_points', 'free_robbery', 'triple_gold',
    'speed_quiz', 'mystery_box'
);

CREATE TABLE special_events (
    event_id        SERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    event_type      event_type NOT NULL,
    description     TEXT,
    multiplier      REAL DEFAULT 1.0,
    starts_at       TIMESTAMP NOT NULL,
    ends_at         TIMESTAMP NOT NULL,
    announced       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_active ON special_events (guild_id, starts_at, ends_at);

-- ============================================================
-- 8. CONFIGURACIÓN POR SERVIDOR
-- ============================================================
CREATE TABLE guild_config (
    guild_id                BIGINT PRIMARY KEY,
    quiz_channel_id         BIGINT,
    gold_channel_id         BIGINT,
    log_channel_id          BIGINT,
    daily_points            INTEGER DEFAULT 10,
    quiz_points             INTEGER DEFAULT 5,
    gold_min_points         INTEGER DEFAULT 25,
    gold_max_points         INTEGER DEFAULT 40,
    robbery_min_pct         REAL DEFAULT 0.10,
    robbery_max_pct         REAL DEFAULT 0.20,
    robbery_fail_pct        REAL DEFAULT 0.05,
    robbery_cooldown_min    INTEGER DEFAULT 60,
    max_robberies_daily     INTEGER DEFAULT 3,
    quiz_cooldown_min       INTEGER DEFAULT 15,
    daily_cooldown_hours    INTEGER DEFAULT 24,
    gold_interval_min       INTEGER DEFAULT 60,
    gold_interval_max       INTEGER DEFAULT 300,
    gold_quiz_chance        REAL DEFAULT 0.05,
    min_money_to_rob        INTEGER DEFAULT 50,
    top_role_ids            JSONB DEFAULT '[]',
    language                VARCHAR(5) DEFAULT 'es',
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 9. TRANSACCIONES
-- ============================================================
CREATE TABLE transactions (
    tx_id           SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    guild_id        BIGINT NOT NULL,
    tx_type         VARCHAR(30) NOT NULL,
    points_delta    INTEGER NOT NULL DEFAULT 0,
    money_delta     INTEGER NOT NULL DEFAULT 0,
    description     TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT transactions_user_fk
        FOREIGN KEY(user_id, guild_id) REFERENCES users(user_id, guild_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_tx_user ON transactions (user_id, guild_id, created_at DESC);
CREATE INDEX idx_tx_type ON transactions (tx_type, created_at DESC);

-- ============================================================
-- 10. DAILY RESET HELPER
-- ============================================================
CREATE OR REPLACE FUNCTION reset_daily_counters()
RETURNS void AS $$
BEGIN
    UPDATE users SET robberies_today = 0
    WHERE robberies_today > 0;
END;
$$ LANGUAGE plpgsql;