## Steps to setup the project
- Download python 3.12.0 (https://www.python.org/downloads/release/python-3120/). Note: latest version 3.13 is causing conflicts for some libraries, so for now you need python 3.12
- Download postgres latest https://www.postgresql.org/download/ and setup postgresql.
- Download Docker (https://docs.docker.com/get-started/get-docker/) and install docker.
- Run docker-compose up ( this will create the container for the postgres vector database)
- Verify if the container is up by running "docker ps".
- Install dependencies by using pip install -r requirements.txt
- Create virtual environment in Visual Code ctrl+shift+p.
- Create Venv environment
- Add below the PGVector connection in the activate.bat
set PGVECTOR_CONNECTION=postgresql+psycopg://postgres:test@localhost:5432/smartmatch

- Activate the virtual environment by running ".\.venv\Scripts\activate.bat" in the cmd.
- Run "python main.py" to start the application.

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

Ensure this line is in activate.bat
set PGVECTOR_CONNECTION=postgresql+psycopg://postgres:test@localhost:5432/smartmatch

Also ensure you're in virtual env with
.\.venv\Scripts\Activate.ps1  



