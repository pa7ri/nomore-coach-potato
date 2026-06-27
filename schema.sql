-- Schema for nomore-coach-potato. Idempotent; safe to run on every boot.

CREATE TABLE IF NOT EXISTS plans (
  id            BIGSERIAL PRIMARY KEY,
  title         TEXT NOT NULL,
  description   TEXT,
  starts_at     TIMESTAMPTZ NOT NULL,
  duration_min  INTEGER,
  price_cents   INTEGER,
  currency      TEXT DEFAULT 'EUR',
  location      TEXT,
  link          TEXT,
  created_by    BIGINT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS plans_starts_at_idx ON plans (starts_at);

CREATE TABLE IF NOT EXISTS movies (
  id          BIGSERIAL PRIMARY KEY,
  title       TEXT NOT NULL,
  note        TEXT,
  link        TEXT,
  watched_at  TIMESTAMPTZ,
  added_by    BIGINT NOT NULL,
  added_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS movies_watched_idx ON movies (watched_at);
