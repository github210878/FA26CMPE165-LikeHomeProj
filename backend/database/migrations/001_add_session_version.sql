USE likehome_db;

-- Run once against an existing database created before session_version existed.
ALTER TABLE users
    ADD COLUMN session_version INT NOT NULL DEFAULT 0;
