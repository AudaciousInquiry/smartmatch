## Steps to setup the project
- Download python 3.12.0 (https://www.python.org/downloads/release/python-3120/). Note: latest version 3.13 is causing conflicts for some libraries, so for now you need python 3.12
- Download postgres latest https://www.postgresql.org/download/ and setup postgresql.
- Download Docker (https://docs.docker.com/get-started/get-docker/) and install docker.
- Run docker-compose up ( this will create the container for the postgres vector database)
- Verify if the container is up by running "docker ps".
- Create virtual environment in Visual Code ctrl+shift+p.
- Create Venv environment
- Add below the PGVector connection in the activate.bat
set PGVECTOR_CONNECTION=postgresql+psycopg://postgres:test@localhost:5432/smartmatch

- Activate the virtual environment by running ".\.venv\Scripts\activate.bat" in the cmd.
- Run "python main.py" to start the application.

