# E2E Transfer CLI

## Prerequisites
- RHEL 9
- Python 3.9+

## Setup (Online)
1. `python3 -m venv venv`
2. `source venv/bin/activate`
3. `pip install -r requirements.txt`

## Setup (Offline)
**On Internet-connected machine:**
```bash
pip download -r requirements.txt -d ./wheelhouse
```

**On Air-gapped RHEL 9:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install --no-index --find-links=./wheelhouse -r requirements.txt
```

## Usage
The utility uses a nested command structure. Use the --help flag at any level to see available options.

**Global Options**

Database connection details can be provided as global flags:

`--host`: MySQL IP (Default: 127.0.0.1).

`--port`: MySQL Port (Default: 3306).

`--user`: Username (Can also use DB_USER env var).

`--password`: Will prompt if not provided (Can also use DB_PASS env var).

**Command Examples**
1. Customer Management

    List all customers and their limits:

    `python3 -m src.main customer list`

    Add a new customer:

    `python3 -m src.main customer add "Client_Alpha"`

2. Transfer Operations

    Manually initiate a transfer record:

    `python3 -m src.main transfer start <customer_id> "payload.zip" 5000000 --node "server-01"`

3. Live Monitoring

    Launch the real-time dashboard:
    python3 -m src.main monitor --n 20 --m 2

    `--n`: Number of recent transfers to show.

    `--m`: Refresh interval in seconds.