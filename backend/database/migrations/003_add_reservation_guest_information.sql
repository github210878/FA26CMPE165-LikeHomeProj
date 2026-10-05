-- Run once on existing databases after migrations 001 and 002 as applicable.
-- Existing reservations retain NULL guest fields; do not infer contacts from users.
ALTER TABLE reservations
    ADD COLUMN guest_full_name VARCHAR(100) NULL,
    ADD COLUMN guest_email VARCHAR(100) NULL;
