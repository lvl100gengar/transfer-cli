DROP DATABASE IF EXISTS e2e_tracking;
CREATE DATABASE e2e_tracking;
USE e2e_tracking;

-- 1. Identity & Limits
CREATE TABLE customers (
    customer_id     BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    customer_name   VARCHAR(255) NOT NULL UNIQUE,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE customer_limits (
    customer_id            BIGINT UNSIGNED PRIMARY KEY,
    max_simultaneous       INT UNSIGNED NOT NULL DEFAULT 10,
    max_bytes_in_transit   BIGINT UNSIGNED NOT NULL DEFAULT 1073741824,
    curr_simultaneous      INT UNSIGNED NOT NULL DEFAULT 0,
    curr_bytes_in_transit  BIGINT UNSIGNED NOT NULL DEFAULT 0,
    timeout_ms             INT UNSIGNED NOT NULL DEFAULT 30000,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE
);

-- 2. Permanent History
CREATE TABLE transfers (
    transfer_id          BINARY(16) PRIMARY KEY,
    customer_id          BIGINT UNSIGNED NOT NULL,
    performed_by         VARCHAR(255) NULL,
    transfer_type        ENUM('LIVE', 'TEST', 'TEST_FORWARD') NOT NULL DEFAULT 'LIVE',
    filename             VARCHAR(512) NOT NULL,
    bytes                BIGINT UNSIGNED NOT NULL,
    status               ENUM(
                           'IN_PROGRESS', 'COMPLETED', 'SERVICE_ERROR',
                           'NO_RESPONSE', 'BAD_REQUEST', 'VALIDATION_FAILED',
                           'UNREACHABLE_DESTINATION'
                         ) NOT NULL DEFAULT 'IN_PROGRESS',
    started_at           DATETIME(3) NOT NULL,
    completed_at         DATETIME(3) NULL,
    started_by_server    VARCHAR(64) NULL,
    completed_by_server  VARCHAR(64) NULL,
    http_status_code     SMALLINT UNSIGNED NULL,
    validation_code      SMALLINT UNSIGNED NULL,
    -- Optimized index for 100 TPS lookups on active transfers
    INDEX idx_active_lookup (status, customer_id, started_at),
    INDEX idx_cust_time (customer_id, started_at)
);

-- 3. Local Response Log (Satellite Instances)
CREATE TABLE local_transfer_responses (
    transfer_id          BINARY(16) PRIMARY KEY,
    status               ENUM(
                           'COMPLETED', 'SERVICE_ERROR', 'BAD_REQUEST', 
                           'VALIDATION_FAILED', 'UNREACHABLE_DESTINATION'
                         ) NOT NULL,
    completed_at         DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    completed_by_server  VARCHAR(64) NOT NULL,
    http_status_code     SMALLINT UNSIGNED NULL,
    validation_code      SMALLINT UNSIGNED NULL,
    INDEX idx_completed (completed_at)
);

-- 4. Automations
DELIMITER //
CREATE TRIGGER after_customer_insert
AFTER INSERT ON customers FOR EACH ROW
BEGIN
    INSERT INTO customer_limits (customer_id) VALUES (NEW.customer_id);
END //
DELIMITER ;