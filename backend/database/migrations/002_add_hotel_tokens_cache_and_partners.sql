USE likehome_db;

-- Run once on databases initialized before hotels.hotel_token, cache_hotels,
-- and hotel_partners were added. Do not run on a fresh database created from
-- like_home_database_init.sql. MySQL DDL commits implicitly, so back up the
-- database and run during a maintenance window.
--
-- Existing hotel IDs and their reservations remain unchanged. legacy:<id> is
-- an internal identifier only; it is never a SerpApi property_token.
ALTER TABLE hotels
    ADD COLUMN hotel_token VARCHAR(255) NULL;

UPDATE hotels
SET hotel_token = CONCAT('legacy:', hotel_id)
WHERE hotel_token IS NULL;

ALTER TABLE hotels
    MODIFY COLUMN hotel_token VARCHAR(255) NOT NULL,
    ADD CONSTRAINT uq_hotels_hotel_token UNIQUE (hotel_token);

CREATE TABLE cache_hotels (
    property_token VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NULL,
    price_per_night DECIMAL(10, 2),
    rating DECIMAL(3, 2),
    amenities JSON,
    hotel_class VARCHAR(50),
    overall_rating DECIMAL(3, 2),
    reviews INT,
    rate_per_night JSON,
    total_rate JSON,
    thumbnail TEXT,
    link TEXT,
    gps_coordinates JSON
);

CREATE TABLE hotel_partners (
    partner_id INT AUTO_INCREMENT PRIMARY KEY,
    user_name VARCHAR(100) NOT NULL,
    hotel_token VARCHAR(255) NOT NULL,
    password_hash VARCHAR(500) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hotel_id INT NOT NULL,
    FOREIGN KEY (hotel_id) REFERENCES hotels (hotel_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);
