-- core/migrations/0003_seed_subscribers.sql
INSERT INTO subscribers (url, secret, enabled, created_at) VALUES
    ('http://localhost:9001/webhook', 'dev-secret-1', '1', datetime('now')),
    ('http://localhost:9002/webhook', 'dev-secret-2', '1', datetime('now')),
    ('http://localhost:9003/webhook', 'dev-secret-3', '1', datetime('now')),
    ('http://localhost:9004/webhook', 'dev-secret-4', '1', datetime('now')),
    ('http://localhost:9005/webhook', 'dev-secret-5', '0', datetime('now'));