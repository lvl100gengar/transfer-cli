# E2E Transfer Tracking CLI

A high-performance CLI tool for tracking end-to-end data transfers. This application manages customer concurrency limits and bandwidth quotas in real-time, utilizing a MariaDB/MySQL backend with specialized stored procedures to handle high-concurrency environments.

## Prerequisites

- RHEL 9
- Python 3.9+
- MySQL Server 8.0

## Offline Deployment Setup

Follow these instructions to deploy the application on a target system (such as RHEL 9) that does not have internet access.

### Source System: Download Dependencies

On a machine with internet access, download the required Python wheels into a directory named wheelhouse.

```bash
mkdir wheelhouse
pip download -r requirements.txt -d ./wheelhouse
```

### Target System: Database Initialization

Before running the application, you must initialize the database schema and logic. Transfer the provided SQL files to your database server and execute them in the following order:

- `schema.sql`: Creates the necessary tables and triggers.

- `procedures.sql`: Defines the stored procedures for starting and completing transfers.

```bash
mysql -u root -p e2e_tracking < schema.sql
mysql -u root -p e2e_tracking < procedures.sql
```

### Target System: Create Virtual Environment

Transfer the project files and the wheelhouse directory to the offline target. Use the following commands to create a self-contained environment.

```bash
# Navigate to the project root
cd /path/to/e2e-transfer-app

# Create a virtual environment without pip
python3 -m venv venv
source venv/bin/activate

# Install dependencies from the local wheelhouse
pip install --no-index --find-links=./wheelhouse -r requirements.txt
```
### Initialize Launcher

Ensure the e2e-track wrapper script is executable. This script allows you to run the application using the virtual environment's Python automatically without manual activation.

```bash
chmod +x e2e-track
```
## Configuration

Create a config.ini file in the project root to store your database connection details.

```ini
[database]
host = 127.0.0.1
port = 3306
user = transfer_user
database = e2e_tracking
password = my_pass
```

Note: Environment variables can be used for these options using the `export` command. See `./e2e-track --help` for the list of environment variables available.

## Command Overview

The application uses a flattened, alphabetically sorted command structure for direct access to all functions.
Use `./e2e-track --help` to see a complete list of options and commands.

### Customer Management

- `customer-add`: Register a new customer and set their initial limits including concurrency, bandwidth bytes, and timeout.

- `customer-delete`: Permanently remove a customer and their associated limits from the system by name.

- `customer-list`: Display all registered customers, their IDs, and current quota usage in a formatted table.

- `customer-update`: Update the transfer limits (concurrency, bandwidth bytes, and timeout) for an existing customer by name.

### Transfer Operations

- `transfer-start`: Initiate a new transfer record. This validates customer quotas against the database before proceeding.

- `transfer-complete`: Finalize a transfer by its UUID, releasing the allocated quota back to the customer.

- `transfer-list`: View a log of recent transfers. Includes a `--filter` option to search across all columns including UUID, Status, and Filename.

### Monitoring

- `monitor`: Launch a live-updating dashboard to observe real-time quota saturation and system activity across all nodes.