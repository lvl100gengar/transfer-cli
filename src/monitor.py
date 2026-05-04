import time
from datetime import datetime
from rich.live import Live
from rich.table import Table
from rich.console import Console, Group
from rich.panel import Panel

def format_bytes(n):
    """Helper to show MB/GB for readability."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if n < 1024: return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"

def format_ts_slim(ts):
    if not ts: return "-"
    # %-m, %-d, %-H work on Linux (RHEL) to remove leading zeros
    return ts.strftime('%-m-%-d %H:%M:%S')

class LiveMonitor:
    def __init__(self, db_manager):
        self.db = db_manager
        self.console = Console()


    def format_ts(self, ts):
        """Shortens timestamp to MM-DD HH:MM:SS"""
        return ts.strftime('%m-%d %H:%M:%S') if ts else "-"


    def generate_usage_table(self):
        usage_data = self.db.get_customer_usage()
        table = Table(box=None, padding=(0, 2))
        table.add_column("Customer", style="bold white")
        table.add_column("Transfers (Use/Lim)", justify="center")
        table.add_column("Bandwidth (Use/Lim)", justify="center")
        table.add_column("Response Timeout (ms)", justify="center")

        for u in usage_data:
            # Transfer Count logic
            count_color = "red" if u['current_count'] >= u['limit_count'] else "green"
            count_str = f"[{count_color}]{u['current_count']}/{u['limit_count']}[/]"

            # Byte logic
            curr_b = u['current_bytes'] or 0
            lim_b = u['limit_bytes']
            byte_color = "red" if curr_b >= lim_b else "green"
            byte_str = f"[{byte_color}]{format_bytes(curr_b)}/{format_bytes(lim_b)}[/]"

            table.add_row(u['customer_name'], count_str, byte_str, f"{u['timeout_ms']}")
        
        return Panel(table, title="[bold blue]Active Quota Usage[/]", border_style="blue")
    

    def generate_table(self, limit):
        log_table = Table(title="[bold magenta]Recent Activity Log[/]", expand=True)
        transfers = self.db.get_recent_transfers(limit)
        
        # Add a timestamp to the title to show live updates
        now = datetime.now().strftime('%H:%M:%S')
        
        log_table.add_column("ID", style="dim")
        log_table.add_column("Started")
        log_table.add_column("Done")
        log_table.add_column("Customer")
        log_table.add_column("Status")
        log_table.add_column("Codes (H/V)", justify="center") # Compact codes
        log_table.add_column("File")

        for t in transfers:
            # Color logic based on status
            color = "green" if t['status'] == "COMPLETED" else "yellow"
            if t['status'] in ["SERVICE_ERROR", "UNREACHABLE_DESTINATION", "VALIDATION_FAILED"]:
                color = "red"
            
            # Compact status codes: e.g., "200 / 0"
            codes = f"{t['http_status_code'] or '-'}/{t['validation_code'] or '-'}"
            cust_user = f"{t['customer_name']} [dim]({t['performed_by'] or 'self'})[/dim]"

            log_table.add_row(
                t['uuid'],
                format_ts_slim(t['started_at']),
                format_ts_slim(t['completed_at']),
                cust_user,
                f"[{color}]{t['status']}[/{color}]",
                codes,
                t['filename']
            )

        # Combine the usage panel and the log table into one display group
        now = datetime.now().strftime('%H:%M:%S')
        return Group(
            self.generate_usage_table(),
            log_table,
            f"\n[dim]Last Update: {now} | Press Ctrl+C to exit[/]"
        )
    

    def render(self, limit, interval):
        last_render = None
        try:
            with Live(self.generate_table(limit), screen=True, auto_refresh=False) as live:
                while True:
                    last_render = self.generate_table(limit)
                    live.update(last_render, refresh=True)
                    time.sleep(interval)
        except KeyboardInterrupt:
            if last_render:
                self.console.print("\n[bold yellow]Final Snapshot Recorded:[/]")
                self.console.print(last_render)