USE e2e_tracking;

DROP PROCEDURE IF EXISTS start_transfer;
DROP PROCEDURE IF EXISTS complete_transfer;
DROP PROCEDURE IF EXISTS log_local_response;
DROP EVENT IF EXISTS reaper_abandoned_transfers;

DELIMITER //

-- [SOURCE SERVER] Start Transfer (REVISED)
CREATE PROCEDURE start_transfer(
    IN  p_customer_name   VARCHAR(255),
    IN  p_performed_by    VARCHAR(255),
    IN  p_transfer_type   VARCHAR(20),
    IN  p_filename        VARCHAR(512),
    IN  p_bytes           BIGINT UNSIGNED,
    IN  p_server_node     VARCHAR(64),
    OUT p_transfer_uuid   CHAR(36),
    OUT p_status          VARCHAR(50),
    OUT p_message         TEXT
)
proc: BEGIN
    DECLARE v_customer_id BIGINT UNSIGNED;
    DECLARE v_max_simul, v_curr_simul, v_timeout_ms INT UNSIGNED;
    DECLARE v_max_bytes, v_curr_bytes BIGINT UNSIGNED;
    DECLARE v_new_bin_id BINARY(16);
    DECLARE v_reaped_count INT DEFAULT 0;
    DECLARE v_reaped_bytes BIGINT UNSIGNED DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN
        GET DIAGNOSTICS CONDITION 1 p_message = MESSAGE_TEXT;
        ROLLBACK;
        SET p_status = 'ERROR';
    END;

    SELECT customer_id INTO v_customer_id FROM customers WHERE customer_name = p_customer_name;
    IF v_customer_id IS NULL THEN
        SET p_status = 'NOT_FOUND', p_message = 'Customer not found'; LEAVE proc;
    END IF;

    START TRANSACTION;

    -- Row-level lock on limits
    SELECT max_simultaneous, max_bytes_in_transit, curr_simultaneous, curr_bytes_in_transit, timeout_ms 
    INTO v_max_simul, v_max_bytes, v_curr_simul, v_curr_bytes, v_timeout_ms
    FROM customer_limits WHERE customer_id = v_customer_id FOR UPDATE;

    -- 1. SELF-HEALING: Clean up expired transfers for this customer
    -- We use a direct subquery to avoid temporary table 're-open' errors in some MySQL versions
    UPDATE transfers 
    SET status = 'NO_RESPONSE', completed_at = NOW(3)
    WHERE customer_id = v_customer_id 
      AND status = 'IN_PROGRESS' 
      AND started_at < NOW(3) - INTERVAL (v_timeout_ms * 1000) MICROSECOND;

    -- 2. RE-SYNC COUNTERS: If you are at 10/10 but transfers show NO_RESPONSE,
    -- recalculate based on ACTUAL in-progress rows to fix desync
    SELECT COUNT(*), COALESCE(SUM(bytes), 0)
    INTO v_curr_simul, v_curr_bytes
    FROM transfers 
    WHERE customer_id = v_customer_id AND status = 'IN_PROGRESS';

    UPDATE customer_limits 
    SET curr_simultaneous = v_curr_simul, 
        curr_bytes_in_transit = v_curr_bytes
    WHERE customer_id = v_customer_id;

    -- 3. VALIDATE LIMITS
    IF v_curr_simul >= v_max_simul OR (v_curr_bytes + p_bytes) > v_max_bytes THEN
        ROLLBACK; SET p_status = 'LIMIT_EXCEEDED', p_message = 'Max simultaneous or bandwidth exceeded'; LEAVE proc;
    END IF;

    -- 4. EXECUTE TRANSFER
    SET v_new_bin_id = UUID_TO_BIN(UUID());
    UPDATE customer_limits 
    SET curr_simultaneous = curr_simultaneous + 1, 
        curr_bytes_in_transit = curr_bytes_in_transit + p_bytes
    WHERE customer_id = v_customer_id;

    INSERT INTO transfers (transfer_id, customer_id, performed_by, transfer_type, filename, bytes, status, started_at, started_by_server)
    VALUES (v_new_bin_id, v_customer_id, p_performed_by, p_transfer_type, p_filename, p_bytes, 'IN_PROGRESS', NOW(3), p_server_node);

    COMMIT;
    SET p_transfer_uuid = CAST(BIN_TO_UUID(v_new_bin_id) AS CHAR(36)), p_status = 'ACCEPTED', p_message = 'Transfer started';
END //

-- [SOURCE SERVER] Finalize Record
CREATE PROCEDURE complete_transfer(
    IN  p_transfer_uuid     CHAR(36),
    IN  p_final_status      ENUM('COMPLETED','SERVICE_ERROR','NO_RESPONSE','BAD_REQUEST','VALIDATION_FAILED','UNREACHABLE_DESTINATION'),
    IN  p_server_node       VARCHAR(64),
    IN  p_http_code         SMALLINT UNSIGNED,
    IN  p_validation_code   SMALLINT UNSIGNED,
    OUT p_result            VARCHAR(50)
)
comp: BEGIN
    DECLARE v_bin_id BINARY(16) DEFAULT UUID_TO_BIN(p_transfer_uuid);
    DECLARE v_cust_id BIGINT UNSIGNED;
    DECLARE v_bytes BIGINT UNSIGNED;
    DECLARE v_active BOOLEAN;

    START TRANSACTION;
    -- Use PK lookup for maximum speed[cite: 2]
    SELECT customer_id, bytes, (status = 'IN_PROGRESS' OR status = 'NO_RESPONSE') 
    INTO v_cust_id, v_bytes, v_active FROM transfers WHERE transfer_id = v_bin_id FOR UPDATE;

    IF v_cust_id IS NULL OR v_active = 0 THEN
        ROLLBACK; SET p_result = 'NOT_FOUND_OR_ALREADY_DONE'; LEAVE comp;
    END IF;

    UPDATE transfers SET status = p_final_status, completed_at = NOW(3), completed_by_server = p_server_node, 
                         http_status_code = p_http_code, validation_code = p_validation_code
    WHERE transfer_id = v_bin_id;

    UPDATE customer_limits SET curr_simultaneous = GREATEST(0, CAST(curr_simultaneous AS SIGNED) - 1),
                               curr_bytes_in_transit = GREATEST(0, CAST(curr_bytes_in_transit AS SIGNED) - v_bytes)
    WHERE customer_id = v_cust_id;

    COMMIT;
    SET p_result = 'UPDATED';
END //

-- [COMPLETING SERVER] Log Egress
CREATE PROCEDURE log_local_response(
    IN  p_transfer_uuid     CHAR(36),
    IN  p_final_status      ENUM('COMPLETED','SERVICE_ERROR','BAD_REQUEST','VALIDATION_FAILED','UNREACHABLE_DESTINATION'),
    IN  p_server_node       VARCHAR(64),
    IN  p_http_code         SMALLINT UNSIGNED,
    IN  p_validation_code   SMALLINT UNSIGNED
)
BEGIN
    REPLACE INTO local_transfer_responses (transfer_id, status, completed_at, completed_by_server, http_status_code, validation_code)
    VALUES (UUID_TO_BIN(p_transfer_uuid), p_final_status, NOW(3), p_server_node, p_http_code, p_validation_code);
END //

-- [SOURCE SERVER] Timeout Reaper
CREATE EVENT reaper_abandoned_transfers ON SCHEDULE EVERY 30 SECOND DO
BEGIN
    -- Uses idx_active_lookup to avoid full table scans[cite: 2]
    CREATE TEMPORARY TABLE IF NOT EXISTS global_reap (cid BIGINT UNSIGNED, tid BINARY(16), b BIGINT UNSIGNED);
    TRUNCATE global_reap;

    INSERT INTO global_reap 
    SELECT t.customer_id, t.transfer_id, t.bytes FROM transfers t 
    JOIN customer_limits cl ON t.customer_id = cl.customer_id
    WHERE t.status = 'IN_PROGRESS' AND t.started_at < NOW(3) - INTERVAL (cl.timeout_ms * 2 * 1000) MICROSECOND;

    UPDATE transfers t JOIN global_reap r ON t.transfer_id = r.tid SET t.status = 'NO_RESPONSE', t.completed_at = NOW(3);

    UPDATE customer_limits cl JOIN (SELECT cid, COUNT(*) as cnt, SUM(b) as b_sum FROM global_reap GROUP BY cid) r ON cl.customer_id = r.cid
    SET cl.curr_simultaneous = GREATEST(0, CAST(cl.curr_simultaneous AS SIGNED) - r.cnt),
        cl.curr_bytes_in_transit = GREATEST(0, CAST(cl.curr_bytes_in_transit AS SIGNED) - r.b_sum);
END //

DELIMITER ;