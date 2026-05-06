import typer
import os
import configparser
from typing import Optional
from src.database import DatabaseManager
from src.monitor import LiveMonitor, format_ts_slim, format_bytes
from rich.table import Table
from rich.console import Console
from rich.panel import Panel

# Global console instance for consistent rendering
console = Console()

app = typer.Typer(
    help="E2E Transfer Tracking CLI - Consistent Monitor Styling",
    no_args_is_help=True,
    rich_markup_mode="rich"
)

db_config = {}

def load_config():
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(__file__), '../config.ini')
    if os.path.exists(config_path):
        config.read(config_path)
        return config['database']
    return {}

@app.callback()
def main(
    host: str = typer.Option(None, help="MySQL Database IP"),
    port: int = typer.Option(None, help="MySQL Database Port"),
    user: str = typer.Option(None, envvar="DB_USER"),
    password: Optional[str] = typer.Option(None, envvar="DB_PASS"),
    database: str = typer.Option(None, help="Database Name")
):
    global db_config
    cfg = load_config()
    db_config = {
        "host": host or cfg.get('host', '127.0.0.1'),
        "port": int(port or cfg.get('port', 3306)),
        "user": user or cfg.get('user', 'root'),
        "password": password or cfg.get('password', None),
        "database": database or cfg.get('database', 'e2e_tracking')
    }

def get_db() -> DatabaseManager:
    if not db_config["password"]:
        db_config["password"] = typer.prompt("Enter database password", hide_input=True)
    return DatabaseManager(**db_config)

# --- Alpha-Sorted Commands with Consistent Styling ---

@app.command("customer-add", help="[bold]Usage:[/] customer-add [NAME] --max-simul [INT] --max-bytes [INT] --timeout-ms [INT]")
def add_customer(
    name: str = typer.Argument(..., metavar="NAME"),
    max_simul: int = typer.Option(10, help="Max simultaneous transfers"),
    max_bytes: int = typer.Option(1073741824, help="Max transit bandwidth in bytes"),
    timeout_ms: int = typer.Option(30000, help="Timeout in milliseconds")
):
    """Add a new customer with optional custom limits."""
    db = get_db()
    db.add_customer(name, max_simul, max_bytes, timeout_ms)
    console.print(f"[bold green]SUCCESS:[/] Customer '{name}' created with custom limits.")

@app.command("customer-delete", help="[bold]Usage:[/] customer-delete [NAME]")
def delete_customer(name: str = typer.Argument(..., metavar="NAME")):
    """Permanently remove a customer by name."""
    if typer.confirm(f"Are you sure you want to delete customer '{name}'?"):
        db = get_db()
        db.delete_customer_by_name(name)
        console.print(f"[bold red]DELETED:[/] Customer '{name}' removed.")


@app.command("customer-list", help="[bold]Usage:[/] customer-list")
def list_customers():
    """List customers matching the 'Active Quota Usage' monitor panel style."""
    db = get_db()
    usage_data = db.get_customer_usage() 
    
    # Matching sizing and justification from the monitor's top panel
    table = Table(box=None, header_style="bold blue")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Customer", style="bold white", ratio=1)
    table.add_column("Transfers (Use/Lim)", justify="center", width=20)
    table.add_column("Bandwidth (Use/Lim)", justify="center", width=25)
    table.add_column("Timeout", justify="right", width=12)

    for u in usage_data:
        # Same color logic as monitor
        count_color = "red" if u['current_count'] >= u['limit_count'] else "green"
        byte_color = "red" if (u['current_bytes'] or 0) >= u['limit_bytes'] else "green"

        table.add_row(
            str(u['customer_id']),
            u['customer_name'], 
            f"[{count_color}]{u['current_count']}/{u['limit_count']}[/]", 
            f"[{byte_color}]{format_bytes(u['current_bytes'] or 0)}/{format_bytes(u['limit_bytes'])}[/]", 
            f"{u['timeout_ms']}ms"
        )
    
    console.print(Panel(table, title="[bold blue]Active Quota Usage[/]", border_style="blue"))


@app.command("customer-update", help="[bold]Usage:[/] customer-update [NAME] --max-simul [INT] --max-bytes [INT] --timeout-ms [INT]")
def update_customer(
    name: str = typer.Argument(..., metavar="NAME"), 
    max_simul: int = typer.Option(10, help="Max simultaneous transfers"),
    max_bytes: int = typer.Option(1073741824, help="Max transit bandwidth in bytes"),
    timeout_ms: int = typer.Option(30000, help="Timeout in milliseconds")
):
    """Update limits for an existing customer by name[cite: 4]."""
    db = get_db()
    if db.update_limits_by_name(name, max_simul, max_bytes, timeout_ms):
        console.print(f"[bold green]UPDATED:[/] Limits for customer '{name}' are now active.")
    else:
        console.print(f"[bold red]ERROR:[/] Customer '{name}' not found.")


@app.command("monitor", help="[bold]Usage:[/] monitor --n [LIMIT] --m [INTERVAL]")
def monitor(
    n: int = typer.Option(15, help="Number of rows to display"), 
    m: int = typer.Option(2, help="Update interval in seconds")
):
    """Launch the live-updating dashboard."""
    db = get_db()
    LiveMonitor(db).render(limit=n, interval=m)

@app.command("transfer-complete", help="[bold]Usage:[/] transfer-complete [UUID] [STATUS] --node [STR] --http-code [INT] --val-code [INT]")
def complete_trans(
    uuid: str = typer.Argument(..., metavar="UUID"), 
    status: str = typer.Argument(..., metavar="STATUS"), 
    node: str = typer.Option("node-01", help="Completing server node"), 
    http_code: int = typer.Option(200, help="Final HTTP status code"), 
    val_code: int = typer.Option(1, help="Validation result code")
):
    """Finalize a transfer record and release capacity."""
    db = get_db()
    result = db.complete_transfer(uuid, status, node, http_code, val_code)
    if result == "UPDATED":
        console.print(f"[bold green]SUCCESS:[/] Transfer {uuid} finalized.")
    else:
        console.print(f"[bold yellow]NOTICE:[/] {result}")


@app.command("transfer-list", help="[bold]Usage:[/] transfer-list --limit [INT] --filter [TEXT]")
def list_transfers(
    limit: int = typer.Option(20, help="Number of records to show"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Search all columns")
):
    """Show transfers matching the 'Activity Log' monitor panel style."""
    db = get_db()
    transfers = db.get_recent_transfers(limit)
    
    # Matching sizing and justification from the monitor's bottom panel[cite: 5]
    table = Table(header_style="bold magenta", box=None)
    table.add_column("TxID", style="dim", width=38, no_wrap=True)
    table.add_column("Started", style="dim", width=12, no_wrap=True)
    table.add_column("Done", style="dim", width=12, no_wrap=True)
    table.add_column("Customer (User)", ratio=1) 
    table.add_column("Status", width=15, justify="left")
    table.add_column("Codes", width=8, justify="center")
    table.add_column("File", ratio=2)

    for t in transfers:
        start_str = format_ts_slim(t['started_at'])
        done_str = format_ts_slim(t['completed_at'])
        uuid_str = t['uuid']
        cust_user = f"{t['customer_name']} ({t['performed_by'] or 'sys'})"
        status = t['status']
        codes = f"{t['http_status_code'] or '-'}/{t['validation_code'] or '-'}"
        filename = t['filename']
        
        if filter:
            search_blob = f"{uuid_str} {start_str} {done_str} {cust_user} {status} {codes} {filename}".lower()
            if filter.lower() not in search_blob:
                continue

        # Status color logic identical to monitor.py[cite: 5]
        color = "green" if status == "COMPLETED" else "yellow"
        if status in ["SERVICE_ERROR", "NO_RESPONSE", "VALIDATION_FAILED", "UNREACHABLE_DESTINATION"]:
            color = "red"

        table.add_row(
            uuid_str,
            start_str, 
            done_str, 
            cust_user, 
            f"[{color}]{status}[/]", 
            codes, 
            filename
        )
    
    console.print(Panel(table, title="[bold magenta]Recent Activity Log[/]", border_style="magenta"))


@app.command("transfer-start", help="[bold]Usage:[/] transfer-start [CUST_NAME] [FILENAME] [SIZE] --user [STR] --node [STR]")
def start_trans(
    cust_name: str = typer.Argument(..., metavar="CUST_NAME"), 
    filename: str = typer.Argument(..., metavar="FILENAME"), 
    size: int = typer.Argument(..., metavar="SIZE"), 
    user: str = typer.Option("admin", help="User name"), 
    node: str = typer.Option("node-01", help="Source server node")
):
    """Execute a new transfer and increment customer counters."""
    db = get_db()
    uuid, status, msg = db.start_transfer(cust_name, user, "LIVE", filename, size, node)
    if status == "ACCEPTED":
        console.print(f"[bold green]ACCEPTED:[/] {msg}")
        console.print(f"[dim]UUID: {uuid}[/]")
    else:
        console.print(f"[bold red]REJECTED:[/] {status} - {msg}")

if __name__ == "__main__":
    app()