from mysql.connector import pooling

class DatabaseManager:
    def __init__(self, host, port, user, password, database):
        self.pool = pooling.MySQLConnectionPool(
            pool_name="transfer_pool",
            pool_size=5,
            host=host, port=port, user=user,
            password=password, database=database
        )

    def _execute_proc(self, proc_name, args):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # callproc returns the modified arguments list
            results = cursor.callproc(proc_name, args)
            conn.commit()
            return results
        finally:
            cursor.close()
            conn.close()

    def get_customers(self):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT c.customer_id, c.customer_name, cl.max_simultaneous, cl.timeout_ms 
            FROM customers c 
            JOIN customer_limits cl ON c.customer_id = cl.customer_id
        """)
        res = cursor.fetchall()
        cursor.close()
        conn.close()
        return res

    def delete_customer(self, cust_id):
        """Removes a customer; the FK constraint handles deleting customer_limits."""
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        # customer_limits has ON DELETE CASCADE[cite: 2]
        cursor.execute("DELETE FROM customers WHERE customer_id = %s", (cust_id,))
        conn.commit()
        cursor.close()
        conn.close()

    def update_limits(self, cust_id, max_simul, max_bytes, timeout):
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        query = """UPDATE customer_limits SET max_simultaneous=%s, max_bytes_in_transit=%s, timeout_ms=%s 
                   WHERE customer_id=%s"""
        cursor.execute(query, (max_simul, max_bytes, timeout, cust_id))
        conn.commit()
        cursor.close()
        conn.close()

    def start_transfer(self, cust_name, user, t_type, filename, size, server):
        # Updated to pass customer_name as VARCHAR to match proc start_transfer
        # Args: p_cust_name, p_perf_by, p_type, p_file, p_bytes, p_server, OUT uuid, OUT status, OUT msg
        args = [cust_name, user, t_type, filename, size, server, None, None, None]
        res = self._execute_proc('start_transfer', args)
        return res['start_transfer_arg7'], res['start_transfer_arg8'], res['start_transfer_arg9'] # uuid, status, message

    def complete_transfer(self, t_uuid, status, server, http_code, val_code):
        # Args: p_uuid, p_status, p_server, p_http, p_val, OUT result
        args = [t_uuid, status, server, http_code, val_code, None]
        res = self._execute_proc('complete_transfer', args)
        return res['complete_transfer_arg6'] # result string

    def get_recent_transfers(self, limit=10):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT 
                BIN_TO_UUID(t.transfer_id) as uuid, 
                c.customer_name, 
                t.transfer_type, 
                t.performed_by,
                t.filename, 
                t.status, 
                t.started_at, 
                t.completed_at,
                t.http_status_code,
                t.validation_code
            FROM transfers t
            JOIN customers c ON t.customer_id = c.customer_id
            ORDER BY t.started_at DESC 
            LIMIT %s
        """
        cursor.execute(query, (limit,))
        res = cursor.fetchall()
        cursor.close()
        conn.close()
        return res
    
    def get_local_responses(self, limit=20):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT 
                BIN_TO_UUID(transfer_id) as uuid, 
                status, 
                completed_at, 
                completed_by_server,
                http_status_code, 
                validation_code
            FROM local_transfer_responses 
            ORDER BY completed_at DESC LIMIT %s
        """
        cursor.execute(query, (limit,))
        res = cursor.fetchall()
        cursor.close()
        conn.close()
        return res
    
    def get_customer_usage(self):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        # Refactored to use new counters in customer_limits instead of joining in_transit_transfers
        query = """
            SELECT
                c.customer_id,
                c.customer_name,
                cl.curr_simultaneous as current_count,
                cl.max_simultaneous as limit_count,
                cl.curr_bytes_in_transit as current_bytes,
                cl.max_bytes_in_transit as limit_bytes,
                cl.timeout_ms
            FROM customers c
            JOIN customer_limits cl ON c.customer_id = cl.customer_id
        """
        cursor.execute(query)
        res = cursor.fetchall()
        cursor.close()
        conn.close()
        return res
    
    def get_customer_by_name(self, name):
        """Helper to resolve name to ID."""
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT customer_id FROM customers WHERE customer_name = %s", (name,))
        res = cursor.fetchone()
        cursor.close()
        conn.close()
        return res['customer_id'] if res else None

    def add_customer(self, name, max_simul=10, max_bytes=1073741824, timeout=30000):
        """Adds a customer and immediately sets their limits[cite: 2, 3]."""
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        # Trigger after_customer_insert creates default limits row[cite: 2]
        cursor.execute("INSERT INTO customers (customer_name) VALUES (%s)", (name,))
        cust_id = cursor.lastrowid
        
        # Update those defaults with the provided custom values
        query = """UPDATE customer_limits SET max_simultaneous=%s, max_bytes_in_transit=%s, timeout_ms=%s 
                WHERE customer_id=%s"""
        cursor.execute(query, (max_simul, max_bytes, timeout, cust_id))
        conn.commit()
        cursor.close()
        conn.close()

    def delete_customer_by_name(self, name):
        """Removes a customer by name[cite: 3]."""
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM customers WHERE customer_name = %s", (name,))
        conn.commit()
        cursor.close()
        conn.close()

    def update_limits_by_name(self, name, max_simul, max_bytes, timeout):
        """Updates limits using the customer name[cite: 3]."""
        cust_id = self.get_customer_by_name(name)
        if not cust_id:
            return False
        self.update_limits(cust_id, max_simul, max_bytes, timeout)
        return True