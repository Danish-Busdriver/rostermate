CREATE TABLE IF NOT EXISTS rostermate_installations (
    installation_hash CHAR(64) PRIMARY KEY,
    platform VARCHAR(16) NOT NULL,
    app_version VARCHAR(32) NOT NULL,
    first_seen_at DATETIME NOT NULL,
    last_seen_at DATETIME NOT NULL,
    heartbeat_count INT UNSIGNED NOT NULL DEFAULT 1,
    INDEX idx_last_seen_at (last_seen_at),
    INDEX idx_app_version (app_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rostermate_heartbeat_daily (
    installation_hash CHAR(64) NOT NULL,
    heartbeat_date DATE NOT NULL,
    heartbeat_count INT UNSIGNED NOT NULL DEFAULT 1,
    PRIMARY KEY (installation_hash, heartbeat_date),
    INDEX idx_heartbeat_date (heartbeat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
