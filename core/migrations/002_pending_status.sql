ALTER TABLE events
ADD queue_status TEXT NOT NULL DEFAULT 'pending';
