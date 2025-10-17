## Running the project's various services

### Option 1: Full Docker Stack (No environment setup needed)
```shell
# Run database, backend API application, and frontend UI in Docker
docker compose up -d

# Access Frontend at: http://localhost:3000
# Access API at: http://localhost:8000 (Note, no route is defined for / so don't expect an interesting response...try /rfps, /schedule, /email-settings, /scrape, or see /docs for more options)
# API docs at: http://localhost:8000/docs
```

### Option 2: Database in Docker + Local Development
```shell
# Run database only in Docker
docker compose up -d postgres

# Run API locally (more common for development)
python -m uvicorn service:app --reload --port 8000

# Run CLI locally
python main.py
# Note: many other arg options, see file
```

### Option 3: Local Development Only
```shell
# Config Console (run from within the rfp-console folder)
npm run dev

# API (local Python)
python -m uvicorn service:app --reload --port 8000

# CLI (local Python)
python main.py
# Note: many other arg options, see file
```

### Docker Command Reference
```shell
# Start full stack (database + API + frontend)
docker compose up -d

# Start only specific services
docker compose up -d postgres          # Database only
docker compose up -d postgres app      # Database + API only

# Stop services
docker compose down

# Rebuild and start (needed after code changes to Dockerfile, docker-compose, or adding/removing npm packages in the frontend)
docker compose up -d --build

# View logs (basic)
docker compose logs app                      # API logs
docker compose logs frontend                 # Frontend logs
docker compose logs postgres                 # Database logs
docker compose logs -f                       # Follow all logs in real-time
docker compose logs app --tail 20 --follow   # Most useful: last 20 lines + follow
```

For comprehensive Docker logging commands and scenarios, see [Docker Logging Guide](docker-logging.md).

## Steps to setup a fully containerized environment
- Download, install, and open Docker (https://docs.docker.com/get-started/get-docker/)
- Clone the repo
- Copy environment variables from the .env.template to a .env file that you create (it is git-ignored) and add missing values to your personal .env file
  - Note: Do NOT commit secret values to the .env.template file, only edit the local hidden .env file
- Run "docker compose up" (this will create the database, backend, and frontend, and install all required software and dependencies)

### (Optional) Final Step: Use VS Code Dev Containers for Development

For the best experience with full intellisense and no local dependency management:

1. Install the "Dev Containers" extension in VS Code.
2. Run `docker compose up -d` first to start all services in the background. Note: If docker is already running from prior steps, that is also fine.
3. Open the project folder in VS Code in a new window.
4. Press `Ctrl+Shift+P` and select "Dev Containers: Reopen in Container".
5. When prompted, choose which dev container config to use:
   - **devcontainer-frontend.json** (Frontend - Node.js environment with npm and all frontend dependencies)
   - **devcontainer-backend.json** (Backend - Python environment with all backend dependencies)
6. VS Code will connect to the selected container and provide full intellisense, type checking, and terminal access.

**When inside a Dev Container:**
- You do NOT need to prefix commands with `docker compose exec` or similar. Just run `npm`, `python`, etc. directly in the VS Code terminal.
- All dependencies are already installed in the container.
- For full-stack development, open two VS Code windows—one connected to frontend and one to backend.
- Ports are automatically forwarded (3000 for frontend, 8000 for API, 5432 for database).

This approach keeps your local machine clean and ensures your dev environment matches production.

## Steps to setup a (mostly) local environment
- Download python 3.12.0 (https://www.python.org/downloads/release/python-3120/)
  - Note: latest version 3.13 is causing conflicts for some libraries, so for now you need python 3.12
- Download and install node, npm, and nvm
- Download and install Postgresql latest https://www.postgresql.org/download/
- Download, install, and open Docker (https://docs.docker.com/get-started/get-docker/)
- Clone the repo
- Copy environment variables from the .env.template to a .env file that you create (it is git-ignored) and add missing values to your personal .env file
  - Note: Do NOT commit secret values to the .env.template file, only edit the local hidden .env file
- Run "docker compose up postgres" (this will create the container for the postgres vector database)
- Verify the container is up by running "docker ps"
- Create a venv and activate it so we install our dependencies in the right (local) location
- Install dependencies by using "pip install -r requirements.txt"
- Run "python main.py" to start the application or use uvicorn "python -m uvicorn service:app --reload --port 8000" to run the API
- Run "npm run dev" to run the frontend (ensure the API is running if using the frontend)

## Common Commands

### Run the Main Application
```shell
python main.py
```
Runs the application with no emailing, just command line logging.

### Flags for main.py
- `--email` — Sends the user email after scraping if a new RFP was found
- `--debug-email` — Sends the debug email, containing all the logs from a run. Sends even if nothing new was found
- `--list` — Lists everything stored in the DB
- `--clear` — Clears everything stored in the DB

**Examples:**
```shell
python main.py --email
python main.py --debug-email
python main.py --list
python main.py --clear
```

---

## All Available Scripts and Commands

### main.py - Main RFP Scraping Script
The primary script for scraping RFPs from configured websites and managing the database.

```shell
# Run basic scrape (no emails)
python main.py

# Run scrape and send email if new RFPs found
python main.py --email

# Run scrape and send debug email with full logs
python main.py --debug-email

# Send both emails
python main.py --email --debug-email

# List all processed RFPs in the database
python main.py --list

# List all excluded RFPs (expired/out-of-scope/etc.)
python main.py --list-exclusions

# Clear all processed RFPs from database
python main.py --clear

# Clear all excluded RFPs from database
python main.py --clear-exclusions

# Clear/reset the scheduled run configuration
python main.py --clear-schedule
```

**Available Arguments:**
- `--email` - Sends email to main recipients if new RFPs are found
- `--debug-email` - Sends debug email with full logs to debug recipients
- `--list` - Display all processed RFPs from the database
- `--list-exclusions` - Display all excluded RFPs (expired/out-of-scope)
- `--clear` - Remove all processed RFPs from the database
- `--clear-exclusions` - Remove all excluded RFPs from the database
- `--clear-schedule` - Reset the scrape schedule configuration

---

### bedrock_scrape.py - Single URL RFP Probe
Debug tool to analyze a single URL for RFP listings. Useful for testing different parameters or one-off scrapes.

```shell
# Analyze a single URL for RFPs
python bedrock_scrape.py --url "https://example.gov/rfp-opportunities"

# Specify a custom site name
python bedrock_scrape.py --url "https://example.gov/rfps" --site "Example Gov"

# Advanced: Limit text analysis
python bedrock_scrape.py --url "https://example.gov/rfps" --max-text 8000

# Advanced: Limit number of items to process
python bedrock_scrape.py --url "https://example.gov/rfps" --max-items 10
```

**Common Arguments:**
- `--url` (required) - The URL to analyze for RFP listings
- `--site` - Custom site name to store (defaults to domain name)
- `--max-text` - Maximum characters to analyze per page (default: 16000)
- `--max-items` - Maximum number of RFP items to process (default: unlimited)
- `--max-links` - Maximum number of links to analyze (default: 400)
- `--max-hops` - Maximum navigation depth (default: 5)

**Advanced Arguments:**
- `--timeout-read` - Read timeout in seconds (default: 60.0)
- `--timeout-connect` - Connection timeout in seconds (default: 10.0)
- `--retries` - Number of retry attempts (default: 2)
- `--temperature` - LLM temperature setting (default: 0.0)
- `--model-id` - Override default LLM model
- `--region` - AWS region override
- `--log-bedrock-raw` - Enable detailed LLM response logging
- `--log-bedrock-raw-chars` - Characters to log from LLM responses (default: 2000)

---

## Running Python Scripts: Docker vs Local

### Running a Script Inside Docker
All dependencies from `requirements.txt` are installed in the Docker container. To run a script (e.g., `bedrock_scrape.py`) inside the container, use:

```shell
docker compose run --rm app python bedrock_scrape.py --url "https://www.tn.gov/generalservices/procurement/central-procurement-office--cpo-/supplier-information/request-for-proposals--rfp--opportunities1"
```
- This ensures all dependencies are available.
- Replace the script name and arguments as needed.

### Running a Script Locally
If you want to run scripts directly on your machine (outside Docker), you must install all dependencies yourself:

```shell
# (Recommended) Create and activate a virtual environment first
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run your script
python bedrock_scrape.py --url "https://www.tn.gov/generalservices/procurement/central-procurement-office--cpo-/supplier-information/request-for-proposals--rfp--opportunities1"
```
- If you see `ModuleNotFoundError`, it means you need to install the missing package (see above)
- Keeping your local environment in sync with Docker is your responsibility if you choose this route

---

## Troubleshooting

### PGVECTOR NOT INSTALLED
If you see an error like:

```
DETAIL:  Could not open extension control file "C:/Program Files/PostgreSQL/17/share/extension/vector.control": No such file or directory.
HINT:  The extension must first be installed on the system where PostgreSQL is running.
[SQL: SELECT pg_advisory_xact_lock(...); CREATE EXTENSION IF NOT EXISTS vector;]
```

This usually means you are connecting to a native Windows PostgreSQL install instead of the Docker container (which has pgvector enabled). The native install may have bound to the port first.

**To fix:**
1. Stop the native Windows PostgreSQL service:
   ```powershell
   Stop-Service -Name postgresql-x64-17 -Force
   ```
2. Bring down Docker and remove the old volume:
   ```shell
   docker-compose down
   docker volume rm smartmatchai_pgdata
   docker-compose up --build
   ```

### EXECUTION POLICIES ERROR ON VIRTUAL ENVIRONMENT CREATION
If you see an error like:

```
.venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled on this system.
For more information, see about_Execution_Policies at https:/go.microsoft.com/fwlink/?LinkID=135170.
```

**To fix:**
Run this command in PowerShell:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

### CREDENTIALS ISSUE
If you see an error like:

```
Exception: Failed to create vector extension: (psycopg.OperationalError) connection failed: ... port 5432 failed: FATAL:  password authentication failed for user "postgres"
```

**To fix:**
- Ensure the `PGVECTOR_CONNECTION` environment variable is set in your local `.env` file, for example:
  ```env
  PGVECTOR_CONNECTION=postgresql+psycopg://postgres:test@localhost:5433/smartmatch
  ```
- Make sure you are in your virtual environment:
  ```shell
  .\.venv\Scripts\Activate.ps1
  ```

