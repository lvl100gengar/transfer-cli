from mysql.connector import pooling

class DatabaseManager:
    def __init__(self, host, port, user, password, database):
        self.pool = pooling.MySQLConnectionPool(
            pool_name="transfer_pool",
            pool_size=5,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )

    def _execute_proc(self, proc_name, args):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            results = cursor.callproc(proc_name, args)
            conn.commit()
            return results
        finally:
            cursor.close()
            conn.close()

    def add_customer(self, name):
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO customers (customer_name) VALUES (%s)", (name,))
        conn.commit()
        cursor.close()
        conn.close()

    def get_customers(self):
        conn = self.pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT c.customer_id, c.customer_name, cl.max_simultaneous, cl.timeout_ms FROM customers c JOIN customer_limits cl ON c.customer_id = cl.customer_id")
        res = cursor.fetchall()
        cursor.close()
        conn.close()
        return res

    def update_limits(self, cust_id, max_simul, max_bytes, timeout):
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        query = """UPDATE customer_limits SET max_simultaneous=%s, max_bytes_in_transit=%s, timeout_ms=%s 
                   WHERE customer_id=%s"""
        cursor.execute(query, (max_simul, max_bytes, timeout, cust_id))
        conn.commit()
        cursor.close()
        conn.close()

    def start_transfer(self, cust_id, user, t_type, filename, size, server):
        # Args: p_cust_id, p_perf_by, p_type, p_file, p_bytes, p_server, OUT uuid, OUT status, OUT msg
        args = [cust_id, user, t_type, filename, size, server, 0, '', '']
        res = self._execute_proc('start_transfer', args)
        return res['start_transfer_arg7'], res['start_transfer_arg8'], res['start_transfer_arg9'] # uuid, status, message

    def complete_transfer(self, t_uuid, status, server, http_code, val_code):
        args = [t_uuid, status, server, http_code, val_code, '']
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
        # Note: local_transfer_responses only exists on completing servers
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
        query = """
            SELECT 
                c.customer_name,
                COUNT(i.transfer_id) as current_count,
                cl.max_simultaneous as limit_count,
                SUM(COALESCE(i.bytes, 0)) as current_bytes,
                cl.max_bytes_in_transit as limit_bytes,
                cl.timeout_ms
            FROM customers c
            JOIN customer_limits cl ON c.customer_id = cl.customer_id
            LEFT JOIN in_transit_transfers i ON c.customer_id = i.customer_id
            GROUP BY c.customer_id
        """
        cursor.execute(query)
        res = cursor.fetchall()
        cursor.close()
        conn.close()
        return res