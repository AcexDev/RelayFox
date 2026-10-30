ALTER TABLE events ADD COLUMN next_attempt_at TEXT;

CREATE INDEX idx_events_due ON events(status, next_attempt_at);
