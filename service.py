from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import (
    create_engine, Table, Column, String, Integer, Boolean,
    DateTime, JSON, MetaData, select, update, insert
)
import datetime
import hashlib
import os
from typing import List, Optional

from main import main, process_and_email
from email_utils import send_email
from configuration_values import ConfigurationValues
from loguru import logger

app = FastAPI(title="SmartMatch Admin API")

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
        return {
            "enabled": row.enabled,
            "interval_hours": row.interval_hours,
        }

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
def trigger_scrape(send_main: Optional[bool] = True, send_debug: Optional[bool] = False):
    new_rfps = run_scrape() 
    main_body = format_new_rfps(new_rfps)
    with engine.connect() as conn:
        email_conf = get_or_create_email_settings(conn)
    if send_main and new_rfps:
        send_email("SmartMatch: New RFPs Found", main_body, email_conf.main_recipients)
    if send_debug:
        full_log = "" 
        debug_body = f"{main_body}\n\n--- FULL LOG ---\n{full_log}"
        send_email("SmartMatch: Debug Log", debug_body, email_conf.debug_recipients)
    with engine.begin() as conn:
        now = datetime.datetime.utcnow()
        row = get_or_create_config(conn)
        interval = row.interval_hours
        next_run = now + datetime.timedelta(hours=interval)
        conn.execute(
            update(scrape_config)
            .where(scrape_config.c.id == "singleton")
            .values(last_run_at=now, next_run_at=next_run, updated_at=datetime.datetime.utcnow())
        )
    return {"new_count": len(new_rfps), "new_rfps": new_rfps}
