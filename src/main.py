import typer
from typing import Optional
from src.database import DatabaseManager
from src.monitor import LiveMonitor, format_ts_slim
from rich.table import Table
from rich.console import Console

app = typer.Typer(help="E2E Transfer Tracking CLI for RHEL 9")
cust_app = typer.Typer(help="Manage Customers and Limits")
trans_app = typer.Typer(help="Execute and Track Transfers")
app.add_typer(cust_app, name="customer")
app.add_typer(trans_app, name="transfer")

# Global configuration holders
db_config = {}

@app.callback()
def main(
    host: str = typer.Option("127.0.0.1", help="MySQL Database IP"),
    port: int = typer.Option(3306, help="MySQL Database Port"),
    user: str = typer.Option("root", envvar="DB_USER"),
    password: Optional[str] = typer.Option(None, envvar="DB_PASS", help="DB Password"),
    database: str = typer.Option("e2e_tracking", help="Database Name")
):
    """Global configuration. Subcommands will prompt for password if DB_PASS is missing."""
    global db_config
    db_config = {
        "host": host, "port": port, "user": user, 
        "password": password, "database": database
    }

def get_db() -> DatabaseManager:
    """Lazily initializes the DB. Prompts for password only if needed."""
    if not db_config["password"]:
        db_config["password"] = typer.prompt("Enter database password", hide_input=True)
    return DatabaseManager(**db_config)

@cust_app.command("list")
def list_customers():
    db = get_db()
    customers = db.get_customers()
    for c in customers:
        typer.echo(f"ID: {c['customer_id']} | Name: {c['customer_name']} | Limit: {c['max_simultaneous']}")

@cust_app.command("add")
def add_customer(name: str):
    db = get_db()
    db.add_customer(name)
    typer.echo(f"Customer {name} added successfully.")

@trans_app.command("start")
def start_trans(cust_id: int, filename: str, size: int, user: str = "admin", node: str = "node-01"):
    db = get_db()
    uuid, status, msg = db.start_transfer(cust_id, user, "LIVE", filename, size, node)
    if status == "ACCEPTED":
        typer.secho(f"SUCCESS: {msg} | UUID: {uuid}", fg=typer.colors.GREEN)
    else:
        typer.secho(f"FAILED: {status} - {msg}", fg=typer.colors.RED)


@trans_app.command("complete")
def complete_trans(
    uuid: str, 
    status: str, 
    node: str = "node-01", 
    http_code: int = 200, 
    val_code: int = 1
):
    """Finalize a transfer record and release customer capacity."""
    db = get_db()
    # Matches the procedure: p_uuid, p_status, p_server, p_http, p_val, OUT result
    result = db.complete_transfer(uuid, status, node, http_code, val_code)
    
    if result == "UPDATED":
        typer.secho(f"SUCCESS: Transfer {uuid} finalized.", fg=typer.colors.GREEN)
    else:
        typer.secho(f"NOTICE: {result}", fg=typer.colors.YELLOW)


@trans_app.command("list")
def list_transfers(limit: int = 20):
    db = get_db()
    console = Console()
    transfers = db.get_recent_transfers(limit)
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Started")
    table.add_column("Done")
    table.add_column("TxID")
    table.add_column("Customer (User)")
    table.add_column("Status")
    table.add_column("Codes")
    table.add_column("File")

    for t in transfers:
        # Use our slim formatter
        start = format_ts_slim(t['started_at'])
        done = format_ts_slim(t['completed_at'])
        
        cust_user = f"{t['customer_name']} ({t['performed_by'] or 'sys'})"
        
        table.add_row(
            start, done, t['uuid'], 
            cust_user, t['status'], 
            f"{t['http_status_code'] or '-'}/{t['validation_code'] or '-'}",
            t['filename']
        )
    console.print(table)


@trans_app.command("list-local")
def list_local_responses(limit: int = 20):
    """Query the local_transfer_responses table on a completing server."""
    db = get_db()
    console = Console()
    responses = db.get_local_responses(limit)
    
    table = Table(title="Local Egress Responses", header_style="bold blue")
    table.add_column("Completed", style="cyan")
    table.add_column("Transaction ID")
    table.add_column("Server")
    table.add_column("Status")
    table.add_column("Codes (H/V)")

    for r in responses:
        table.add_row(
            format_ts_slim(r['completed_at']),
            r['uuid'],
            r['completed_by_server'],
            r['status'],
            f"{r['http_status_code'] or '-'}/{r['validation_code'] or '-'}"
        )
    console.print(table)


@app.command("monitor")
def monitor(n: int = 15, m: int = 2):
    """Launch the live-updating dashboard."""
    db = get_db()
    LiveMonitor(db).render(limit=n, interval=m)

if __name__ == "__main__":
    app()