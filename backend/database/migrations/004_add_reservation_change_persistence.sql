-- Run once on an existing database after migrations 001-003 as applicable.
-- Do not run on a fresh database initialized with the current initialization SQL.
-- Back up and follow ../README.md preflight/application/verification instructions.
-- DDL commits implicitly: this migration is not transactionally rollbackable.
-- InnoDB and MySQL 5.7.8+ JSON support are prerequisites.
USE likehome_db;
SET time_zone = '+00:00';

-- Existing reservations retain all IDs, dates, prices and payment records.
ALTER TABLE reservations
    ADD COLUMN revision INT UNSIGNED NOT NULL DEFAULT 0,
    ADD INDEX ix_reservations_user_dates (user_id, check_in_date, check_out_date);

CREATE TABLE reservation_change_events (
    change_id INT AUTO_INCREMENT PRIMARY KEY,
    reservation_id INT NOT NULL,
    user_id INT NOT NULL,
    booking_payment_id INT NOT NULL,
    quote_jti CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    quote_sha256 BINARY(32) NOT NULL,
    request_sha256 BINARY(32) NOT NULL,
    original_state_sha256 BINARY(32) NOT NULL,
    revision_before INT UNSIGNED NOT NULL,
    revision_after INT UNSIGNED NOT NULL,
    old_room_type_id INT NOT NULL,
    new_room_type_id INT NOT NULL,
    old_check_in_date DATE NOT NULL,
    old_check_out_date DATE NOT NULL,
    new_check_in_date DATE NOT NULL,
    new_check_out_date DATE NOT NULL,
    old_reservation_total DECIMAL(10, 2) NOT NULL,
    new_reservation_total DECIMAL(10, 2) NOT NULL,
    old_payment_obligation DECIMAL(10, 2) NOT NULL,
    new_payment_obligation DECIMAL(10, 2) NOT NULL,
    booking_payment_status_before ENUM('pending', 'paid') NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'USD',
    context_json JSON NOT NULL,
    fresh_quote_json JSON NOT NULL,
    response_json JSON NOT NULL,
    quote_issued_at DATETIME(6) NOT NULL,
    quote_expires_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT uq_change_quote_jti UNIQUE (quote_jti),
    CONSTRAINT uq_change_reservation_revision UNIQUE (reservation_id, revision_after),
    INDEX ix_change_user (user_id, change_id),
    INDEX ix_change_payment (booking_payment_id),
    INDEX ix_change_old_room (old_room_type_id),
    INDEX ix_change_new_room (new_room_type_id),
    CONSTRAINT fk_change_reservation FOREIGN KEY (reservation_id)
        REFERENCES reservations (reservation_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_change_user FOREIGN KEY (user_id)
        REFERENCES users (user_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_change_payment FOREIGN KEY (booking_payment_id)
        REFERENCES payments (payment_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_change_old_room FOREIGN KEY (old_room_type_id)
        REFERENCES room_types (room_type_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_change_new_room FOREIGN KEY (new_room_type_id)
        REFERENCES room_types (room_type_id) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- A primary entry and its optional compensating cancellation entry are distinct.
-- Category and same-event parent validation must also run in future write services.
CREATE TABLE reservation_change_adjustments (
    adjustment_id INT AUTO_INCREMENT PRIMARY KEY,
    change_id INT NOT NULL,
    entry_role ENUM('price_change', 'cancellation_reconciliation') NOT NULL DEFAULT 'price_change',
    reconciles_adjustment_id INT NULL,
    kind ENUM('charge', 'credit') NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    status ENUM('pending', 'paid', 'failed', 'recorded', 'voided') NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    settled_at DATETIME(6) NULL,
    CONSTRAINT uq_adjustment_change_role UNIQUE (change_id, entry_role),
    CONSTRAINT uq_adjustment_reconciliation UNIQUE (reconciles_adjustment_id),
    CONSTRAINT uq_adjustment_id_change UNIQUE (adjustment_id, change_id),
    INDEX ix_adjustment_reconciles (reconciles_adjustment_id, change_id),
    CONSTRAINT fk_adjustment_change FOREIGN KEY (change_id)
        REFERENCES reservation_change_events (change_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_adjustment_reconciles FOREIGN KEY (reconciles_adjustment_id, change_id)
        REFERENCES reservation_change_adjustments (adjustment_id, change_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB;
