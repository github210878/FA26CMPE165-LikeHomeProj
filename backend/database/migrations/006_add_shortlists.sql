
CREATE TABLE IF NOT EXISTS shortlists (
                                          shortlist_id INT AUTO_INCREMENT PRIMARY KEY,
                                          user_id INT NOT NULL,
                                          property_token VARCHAR(255) NOT NULL,

    CONSTRAINT uq_shortlist_user_property
    UNIQUE (user_id, property_token),

    CONSTRAINT fk_shortlist_user
    FOREIGN KEY (user_id)
    REFERENCES users(user_id)
    ON DELETE CASCADE
    );