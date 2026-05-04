USE e2e_tracking;

DROP PROCEDURE IF EXISTS start_transfer;
DROP PROCEDURE IF EXISTS complete_transfer;
DROP PROCEDURE IF EXISTS log_local_response;
DROP EVENT IF EXISTS reaper_abandoned_transfers;

DELIMITER //

-- [SOURCE SERVER] Start Transfer
CREATE PROCEDURE start_transfer(
    IN  p_customer_id     BIGINT UNSIGNED,
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
    DECLARE v_max_simul, v_timeout_ms INT UNSIGNED;
    DECLARE v_max_bytes, v_curr_bytes BIGINT UNSIGNED;
    DECLARE v_new_bin_id BINARY(16);
    DECLARE v_curr_count INT UNSIGNED;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN
        ROLLBACK;
        SET p_status = 'ERROR', p_message = 'SQL Error';
    END;

    START TRANSACTION;
    DELETE FROM in_transit_transfers WHERE customer_id = p_customer_id AND expires_at <= NOW(3);

    SELECT max_simultaneous, max_bytes_in_transit, timeout_ms 
    INTO v_max_simul, v_max_bytes, v_timeout_ms FROM customer_limits WHERE customer_id = p_customer_id;

    SELECT COUNT(*), COALESCE(SUM(bytes), 0) INTO v_curr_count, v_curr_bytes 
    FROM in_transit_transfers WHERE customer_id = p_customer_id;

    IF v_curr_count >= v_max_simul OR (v_curr_bytes + p_bytes) > v_max_bytes THEN
        ROLLBACK; SET p_status = 'LIMIT_EXCEEDED'; LEAVE proc;
    END IF;

    SET v_new_bin_id = UUID_TO_BIN(UUID());
    INSERT INTO in_transit_transfers VALUES (v_new_bin_id, p_customer_id, p_bytes, NOW(3) + INTERVAL (v_timeout_ms * 1000) MICROSECOND);
    INSERT INTO transfers (transfer_id, customer_id, performed_by, transfer_type, filename, bytes, status, started_at, started_by_server)
    VALUES (v_new_bin_id, p_customer_id, p_performed_by, p_transfer_type, p_filename, p_bytes, 'IN_PROGRESS', NOW(3), p_server_node);
    COMMIT;

    SET p_transfer_uuid = CAST(BIN_TO_UUID(v_new_bin_id) AS CHAR(36)), p_status = 'ACCEPTED';
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
    START TRANSACTION;
    UPDATE transfers SET status = p_final_status, completed_at = NOW(3), completed_by_server = p_server_node, 
                         http_status_code = p_http_code, validation_code = p_validation_code
    WHERE transfer_id = v_bin_id AND (status = 'IN_PROGRESS' OR status = 'NO_RESPONSE');
    SET p_result = IF(ROW_COUNT() > 0, 'UPDATED', 'NOT_FOUND_OR_ALREADY_DONE');
    DELETE FROM in_transit_transfers WHERE transfer_id = v_bin_id;
    COMMIT;
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
    UPDATE transfers t JOIN customer_limits cl ON t.customer_id = cl.customer_id
    SET t.status = 'NO_RESPONSE', t.completed_at = NOW(3)
    WHERE t.status = 'IN_PROGRESS' AND t.started_at < NOW(3) - INTERVAL (cl.timeout_ms * 2 * 1000) MICROSECOND;
END //

DELIMITER ;
