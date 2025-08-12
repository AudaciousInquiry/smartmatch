## Running the project's various services

### Option 1: Full Docker Stack (No environment setup needed)
```shell
# Run both database and API in Docker
docker compose up -d

# Access API at: http://localhost:8000
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
# Start full stack
docker compose up -d

# Start only database
docker compose up -d postgres

# Stop services
docker compose down

# Rebuild and start
docker compose up -d --build

# View logs
docker compose logs app
docker compose logs postgres
```

## Steps to setup the project
- Download python 3.12.0 (https://www.python.org/downloads/release/python-3120/). Note: latest version 3.13 is causing conflicts for some libraries, so for now you need python 3.12
- Download postgres latest https://www.postgresql.org/download/ and setup postgresql.
- Download Docker (https://docs.docker.com/get-started/get-docker/) and install docker.
- Run docker-compose up (this will create the container for the postgres vector database)
- Verify the container is up by running "docker ps"
- Create a venv and activate it so we install our dependencies in the right (local) location
- Install dependencies by using pip install -r requirements.txt
- Copy environment variables from the .env.template to a .env file that you create (it is git-ignored) and add values to your personal .env file
  - Note: Do NOT commit secret values to the .env.template file, only commit them to the local hidden .env file 
- Run "python main.py" to start the application.

Commands
python main.py  Run application with no emailing, just command line logging

Flags
--email Sends the user email after scraping if a new RFP was found
--debug-email Sends the debug email, containing all the logs from a run. Sends even if nothing new was found
--list Lists everything stored in the DB
--clear Clears everything stored in the DB 


Troubleshooting


PGVECTOR NOT INSTALLED
If the following error is encountered

DETAIL:  Could not open extension control file "C:/Program Files/PostgreSQL/17/share/extension/vector.control": No such file or directory.
HINT:  The extension must first be installed on the system where PostgreSQL is running.
[SQL: SELECT pg_advisory_xact_lock(1573678846307946496);CREATE EXTENSION IF NOT EXISTS vector;]

This is likely because you are attempting to connect to a native Windows PostgreSQL install instead of the docker container that has the pgvector enabled image because the native windows install bound to the port first.

To fix, run the following commands in Powershell  (As admin)
Stop-Service -Name postgresql-x64-17 -Force
cd C:\Users\brocke\Documents\GitHub\SmartMatchAI
docker-compose down
docker volume rm smartmatchai_pgdata
docker-compose up --build


EXECUTION POLICIES ERROR ON VIRTUAL ENVIRONMENT CREATION

If this error is encountered

C:\Users\brocke\Documents\GitHub\SmartMatchAI\.venv\Scripts\Activate.ps1 cannot be loaded because        
running scripts is disabled on this system. For more information, see about_Execution_Policies at        
https:/go.microsoft.com/fwlink/?LinkID=135170.
At line:1 ch

Simply run this command

Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process



CREDENTIALS ISSUE

If getting this

Exception: Failed to create vector extension: (psycopg.OperationalError) connection failed: :1), port 5432 failed: FATAL:  password authentication failed for user "postgres"

Ensure the PGVECTOR_CONNECTION environment variable is set in you local .env file like so:
PGVECTOR_CONNECTION=postgresql+psycopg://postgres:test@localhost:5433/smartmatch

Also ensure you're in virtual env with
.\.venv\Scripts\Activate.ps1  



