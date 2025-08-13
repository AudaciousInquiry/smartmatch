from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy import (
    create_engine, Table, Column, String, Integer, Boolean,
    DateTime, JSON, MetaData, select, update, insert
)
import datetime
import os
from typing import List, Optional
from importlib import reload

from configuration_values import ConfigurationValues
from email_utils import send_email
from main import main as run_scrape_main
from loguru import logger

app = FastAPI(title="SmartMatch Admin API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = create_engine(ConfigurationValues.get_pgvector_connection())
metadata = MetaData(schema="public")

scrape_config = Table(
    "scrape_config", metadata,
    Column("id", String, primary_key=True, default="singleton"),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("interval_hours", Integer, nullable=False, default=24),
    Column("last_run_at", DateTime),
    Column("next_run_at", DateTime),
    Column("created_at", DateTime, default=datetime.datetime.utcnow),
    Column("updated_at", DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow),
)

email_settings = Table(
    "email_settings", metadata,
    Column("id", String, primary_key=True, default="singleton"),
    Column("main_recipients", JSON, nullable=False, default=[]),
    Column("debug_recipients", JSON, nullable=False, default=[]),
    Column("created_at", DateTime, default=datetime.datetime.utcnow),
    Column("updated_at", DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow),
)

processed_rfps = Table(
    "processed_rfps", metadata,
    Column("hash", String, primary_key=True),
    Column("title", String),
    Column("url", String),
    Column("site", String),
    Column("processed_at", String),
)

metadata.create_all(engine)

class ScheduleUpdate(BaseModel):
    enabled: bool
    interval_hours: int

class EmailSettingsUpdate(BaseModel):
    main_recipients: List[EmailStr]
    debug_recipients: List[EmailStr]

def get_or_create_config(conn):
    q = select(scrape_config).where(scrape_config.c.id == "singleton")
    row = conn.execute(q).first()
    if not row:
        conn.execute(
            insert(scrape_config).values(
                id="singleton",
                enabled=True,
                interval_hours=24,
                created_at=datetime.datetime.utcnow(),
                updated_at=datetime.datetime.utcnow(),
            )
        )
        row = conn.execute(q).first()
    return row

def get_or_create_email_settings(conn):
    q = select(email_settings).where(email_settings.c.id == "singleton")
    row = conn.execute(q).first()
    if not row:
        conn.execute(
            insert(email_settings).values(
                id="singleton",
                main_recipients=[],
                debug_recipients=[],
                created_at=datetime.datetime.utcnow(),
                updated_at=datetime.datetime.utcnow(),
            )
        )
        row = conn.execute(q).first()
    return row

@app.get("/rfps")
def list_rfps():
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                processed_rfps.c.processed_at,
                processed_rfps.c.site,
                processed_rfps.c.title,
                processed_rfps.c.url,
                processed_rfps.c.hash,
            ).order_by(processed_rfps.c.processed_at.desc())
        ).mappings().all()
        return [dict(r) for r in rows]

@app.get("/schedule")
def read_schedule():
    with engine.connect() as conn:
        row = get_or_create_config(conn)
        return {
            "enabled": row.enabled,
            "interval_hours": row.interval_hours,
            "last_run_at": row.last_run_at,
            "next_run_at": row.next_run_at,
        }

@app.put("/schedule")
def update_schedule(payload: ScheduleUpdate):
    with engine.begin() as conn:
        conn.execute(
            update(scrape_config)
            .where(scrape_config.c.id == "singleton")
            .values(
                enabled=payload.enabled,
                interval_hours=payload.interval_hours,
                updated_at=datetime.datetime.utcnow(),
            )
        )
        row = conn.execute(select(scrape_config).where(scrape_config.c.id == "singleton")).first()
        return {"enabled": row.enabled, "interval_hours": row.interval_hours}

@app.get("/email-settings")
def get_email_settings():
    with engine.connect() as conn:
        row = get_or_create_email_settings(conn)
        return {
            "main_recipients": row.main_recipients,
            "debug_recipients": row.debug_recipients,
        }

@app.put("/email-settings")
def set_email_settings(payload: EmailSettingsUpdate):
    with engine.begin() as conn:
        conn.execute(
            update(email_settings)
            .where(email_settings.c.id == "singleton")
            .values(
                main_recipients=payload.main_recipients,
                debug_recipients=payload.debug_recipients,
                updated_at=datetime.datetime.utcnow(),
            )
        )
        row = conn.execute(select(email_settings).where(email_settings.c.id == "singleton")).first()
        return {
            "main_recipients": row.main_recipients,
            "debug_recipients": row.debug_recipients,
        }

@app.post("/scrape")
def trigger_scrape(send_main: Optional[bool] = True, send_debug: Optional[bool] = True):
    try:
        import sys
        from pathlib import Path
        
        project_root = str(Path(__file__).parent)
        if project_root not in sys.path:
            sys.path.append(project_root)
        
        import configuration_values
        import main
        reload(configuration_values)
        reload(main)
        
        new_rfps = main.process_and_email(send_main=send_main, send_debug=send_debug)
        
        return {"new_count": len(new_rfps), "new_rfps": new_rfps}
    except Exception as e:
        logger.exception(f"Error during scrape: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
