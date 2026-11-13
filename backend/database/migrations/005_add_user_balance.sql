USE likehome_db;

CREATE TABLE
    user_balances (
        user_id INT PRIMARY KEY,
        balance DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE
    );

CREATE TABLE
    redeem_histories (
        redeem_id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        reward_points_redeemed INT NOT NULL,
        created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        CONSTRAINT fk_redeem_history_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
        CONSTRAINT chk_reward_points_redeemed CHECK (reward_points_redeemed > 0),
        INDEX idx_redeem_history_user_created (user_id, created_at)
    );