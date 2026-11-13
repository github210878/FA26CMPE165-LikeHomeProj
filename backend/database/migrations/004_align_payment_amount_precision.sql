USE likehome_db;

ALTER TABLE payments
    MODIFY COLUMN amount DECIMAL(10, 2) NOT NULL;
