USE likehome_db;

ALTER TABLE redeem_histories
    ADD COLUMN redemption_type VARCHAR(32) NOT NULL DEFAULT 'wallet',
    ADD COLUMN payment_id INT NULL,
    ADD COLUMN reservation_id INT NULL,
    ADD CONSTRAINT fk_redeem_history_payment
        FOREIGN KEY (payment_id) REFERENCES payments (payment_id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_redeem_history_reservation
        FOREIGN KEY (reservation_id) REFERENCES reservations (reservation_id)
        ON DELETE SET NULL ON UPDATE CASCADE;

CREATE INDEX idx_redeem_history_payment
    ON redeem_histories (payment_id);

CREATE INDEX idx_redeem_history_reservation
    ON redeem_histories (reservation_id);