USE likehome_db;

-- Existing bookings lack trusted destination and occupancy data.
ALTER TABLE reservations ADD COLUMN booking_context JSON NULL;
