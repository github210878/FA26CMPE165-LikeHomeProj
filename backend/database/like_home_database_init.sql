CREATE DATABASE IF NOT EXISTS likehome_db;
USE likehome_db;


CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(500) NOT NULL,
    full_name VARCHAR(100),
    phone VARCHAR(30),
    reward_points INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status ENUM(
        'active',
        'deleted'
    ) NOT NULL DEFAULT 'active'
);


CREATE TABLE hotels (
    hotel_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description VARCHAR(5000),
    street VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    country VARCHAR(100) DEFAULT 'USA',
    phone VARCHAR(100)
);


CREATE TABLE room_types (
    room_type_id INT AUTO_INCREMENT PRIMARY KEY,
    hotel_id INT NOT NULL,
    type_name VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    capacity INT NOT NULL,
    price_per_night DECIMAL(10,2) NOT NULL,
    total_rooms INT NOT NULL DEFAULT 1,
    FOREIGN KEY (hotel_id)
        REFERENCES hotels(hotel_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE 
);


CREATE TABLE reservations (
    reservation_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    room_type_id INT NOT NULL,
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    status ENUM(
        'confirmed',
        'cancelled',
        'completed'
    ) NOT NULL DEFAULT 'confirmed',
    total_price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (room_type_id)
        REFERENCES room_types(room_type_id)
        ON DELETE NO ACTION
        ON UPDATE CASCADE,
    CHECK (check_out_date > check_in_date)
);


CREATE TABLE payments (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    reservation_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    payment_type ENUM(
        'booking',
        'cancellation'
    ) NOT NULL,
    payment_status ENUM(
        'pending',
        'paid',
        'failed',
        'refunded'
    ) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (reservation_id)
        REFERENCES reservations(reservation_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);


CREATE TABLE reviews (
	review_id INT AUTO_INCREMENT PRIMARY KEY,
	user_id INT NOT NULL,
	hotel_id INT NOT NULL,
	rate DECIMAL(2,1) NOT NULL,
	comment VARCHAR(500),
	FOREIGN KEY(user_id)
		REFERENCES users(user_id)
		ON DELETE RESTRICT
		ON UPDATE CASCADE,
	FOREIGN KEY(hotel_id)
		REFERENCES hotels(hotel_id)
		ON DELETE CASCADE 
		ON UPDATE CASCADE,
	CHECK (rate >= 1 AND rate <= 5)
);
	

CREATE TABLE photos (
	photo_id INT AUTO_INCREMENT PRIMARY KEY,
	hotel_id INT NOT NULL,
	url VARCHAR(500) NOT NULL,
	description VARCHAR(500),
	FOREIGN KEY (hotel_id)
		REFERENCES hotels(hotel_id)
		ON DELETE CASCADE
		ON UPDATE CASCADE 
);
	

