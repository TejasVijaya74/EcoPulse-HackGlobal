CREATE TABLE IF NOT EXISTS api_rate_limit_windows (
    bucket_key VARCHAR(255) PRIMARY KEY,
    window_start BIGINT NOT NULL,
    hit_count INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_api_rate_limit_windows_start
ON api_rate_limit_windows (window_start);
