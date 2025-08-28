from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
import datetime
from sqlalchemy import (
    create_engine, Table, Column, String, Integer, Boolean,
    DateTime, JSON, MetaData, select, update, insert, text,
    LargeBinary, Float
)
from typing import List, Optional
from importlib import reload
from contextlib import asynccontextmanager
import asyncio
import os
from zoneinfo import ZoneInfo  # Py>=3.9

from configuration_values import ConfigurationValues
from email_utils import send_email
from main import main as run_scrape_main
from loguru import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler_task = asyncio.create_task(check_and_run_schedule())
    logger.info("Started scheduler background task")
    
    yield
    
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        logger.info("Scheduler task cancelled")

app = FastAPI(
    title="SmartMatch Admin API",
    lifespan=lifespan
)

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
    Column("interval_hours", Float, nullable=False, default=24.0),  # changed to Float
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
    Column("detail_content", String),
    Column("ai_summary", String),
    Column("pdf_content", LargeBinary)
)

def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE public.processed_rfps 
            ADD COLUMN IF NOT EXISTS detail_content TEXT,
            ADD COLUMN IF NOT EXISTS ai_summary TEXT,
            ADD COLUMN IF NOT EXISTS pdf_content BYTEA;
        """))

app = FastAPI(
    title="SmartMatch Admin API",
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

metadata.create_all(engine)

def get_sched_tz() -> datetime.tzinfo:
    tz_name = os.getenv("SCHEDULE_TIMEZONE") or os.getenv("SCHED_TZ") or os.getenv("TZ")
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            logger.warning(f"Invalid timezone '{tz_name}', falling back to system local tz")
    return datetime.datetime.now().astimezone().tzinfo

class ScheduleUpdate(BaseModel):
    enabled: bool
    interval_hours: float = Field(gt=0)
    next_run_hour: int = Field(ge=0, lt=24)
    next_run_minute: int = Field(ge=0, lt=60)

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
def list_rfps(
    q: str = "", 
    limit: int = 200, 
    sort: str = "processed_at", 
    order: str = "desc"
):
    with engine.connect() as conn:
        query = select(
            processed_rfps.c.processed_at,
            processed_rfps.c.site,
            processed_rfps.c.title,
            processed_rfps.c.url,
            processed_rfps.c.hash,
        )

        if order.lower() == "desc":
            query = query.order_by(processed_rfps.c[sort].desc())
        else:
            query = query.order_by(processed_rfps.c[sort].asc())

        if limit:
            query = query.limit(limit)

        rows = conn.execute(query).mappings().all()
        return [dict(r) for r in rows]

@app.get("/schedule")
def get_schedule():
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM scrape_config WHERE id = 'singleton'")).first()
        if not row:
            raise HTTPException(status_code=404, detail="Schedule not found")
        m = row._mapping
        return {
            "enabled": m.get("enabled"),
            "interval_hours": float(m.get("interval_hours")) if m.get("interval_hours") is not None else None,
            "next_run_at": m.get("next_run_at").isoformat() if m.get("next_run_at") is not None else None,
            "last_run_at": m.get("last_run_at").isoformat() if m.get("last_run_at") is not None else None
        }

@app.put("/schedule")
def update_schedule(payload: ScheduleUpdate):
    try:
        logger.info(f"Received schedule update: {payload}")
        sched_tz = get_sched_tz()
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_srv = now_utc.astimezone(sched_tz)

        # Next occurrence in server-configured timezone (no interval added here)
        candidate_srv = now_srv.replace(
            hour=payload.next_run_hour,
            minute=payload.next_run_minute,
            second=0,
            microsecond=0,
        )
        if candidate_srv <= now_srv:
            candidate_srv += datetime.timedelta(days=1)

        next_run_utc = candidate_srv.astimezone(datetime.timezone.utc)
        logger.info(f"Server TZ: {sched_tz} | Now(srv): {now_srv} | Next(srv): {candidate_srv} | Store(UTC): {next_run_utc}")

        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO scrape_config (id, enabled, interval_hours, next_run_at, last_run_at, created_at, updated_at)
                    VALUES ('singleton', :enabled, :interval_hours, :next_run_at, NULL, :now_utc, :now_utc)
                    ON CONFLICT (id) DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        interval_hours = EXCLUDED.interval_hours,
                        next_run_at = EXCLUDED.next_run_at,
                        last_run_at = NULL,
                        updated_at = EXCLUDED.updated_at
                """),
                {
                    "enabled": payload.enabled,
                    "interval_hours": float(payload.interval_hours),
                    "next_run_at": next_run_utc,
                    "now_utc": now_utc,
                },
            )

            row = conn.execute(text("SELECT enabled, interval_hours, next_run_at FROM scrape_config WHERE id = 'singleton'")).first()
            m = row._mapping
            nr = m.get("next_run_at")
            return {
                "enabled": bool(m.get("enabled")),
                "interval_hours": float(m.get("interval_hours")),
                "next_run_at": (nr.replace(tzinfo=datetime.timezone.utc).isoformat() if nr and nr.tzinfo is None else (nr.isoformat() if nr else None)),
            }
    except Exception as e:
        logger.exception("Failed to update schedule")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/rfps/{hash}")
def get_rfp_detail(hash: str):
    with engine.connect() as conn:
        result = conn.execute(
            select(processed_rfps).where(processed_rfps.c.hash == hash)
        ).first()
        
        if not result:
            raise HTTPException(status_code=404, detail="RFP not found")
            
        row_dict = result._mapping
        
        return {
            "hash": row_dict["hash"],
            "title": row_dict["title"],
            "url": row_dict["url"],
            "site": row_dict["site"],
            "processed_at": row_dict["processed_at"],
            "detail_content": row_dict.get("detail_content"),
            "ai_summary": row_dict.get("ai_summary"),
            "has_pdf": row_dict.get("pdf_content") is not None
        }

@app.get("/rfps/{hash}/pdf")
def get_rfp_pdf(hash: str):
    with engine.connect() as conn:
        row = conn.execute(
            select(processed_rfps.c.pdf_content, processed_rfps.c.title)
            .where(processed_rfps.c.hash == hash)
        ).first()
        
        if not row or not row.pdf_content:
            raise HTTPException(status_code=404, detail="PDF not found")
        
        from fastapi.responses import Response
        return Response(
            content=row.pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{row.title}.pdf"'
            }
        )

async def check_and_run_schedule():
    logger.info("Scheduler started")
    while True:
        try:
            claimed = False
            next_run_for_log = None

            with engine.begin() as conn:
                row = conn.execute(
                    text("SELECT * FROM scrape_config WHERE id = 'singleton' FOR UPDATE")
                ).first()

                if not row:
                    logger.warning("No schedule configuration found")
                else:
                    m = row._mapping
                    if not m.get("enabled"):
                        logger.debug("Scheduler is disabled")
                    else:
                        now = datetime.datetime.now(datetime.timezone.utc)
                        next_run = m.get("next_run_at")
                        interval_hours = float(m.get("interval_hours") or 0)

                        if next_run and next_run.tzinfo is None:
                            next_run = next_run.replace(tzinfo=datetime.timezone.utc)

                        logger.debug(f"Current time (UTC): {now}")
                        logger.debug(f"Next run time: {next_run}")
                        logger.debug(f"Interval hours: {interval_hours}")

                        if next_run and now >= next_run:
                            new_next = next_run + datetime.timedelta(hours=interval_hours)
                            while new_next <= now:
                                new_next += datetime.timedelta(hours=interval_hours)

                            conn.execute(
                                text("""
                                    UPDATE scrape_config
                                    SET last_run_at = :now,
                                        next_run_at = :new_next_at,
                                        updated_at = :now
                                    WHERE id = 'singleton'
                                """),
                                {"now": now, "new_next_at": new_next}
                            )

                            claimed = True
                            next_run_for_log = next_run
                            logger.info(f"Scheduled run claimed for next_run={next_run} -> new_next={new_next}")

            if claimed:
                try:
                    import sys
                    from pathlib import Path
                    from importlib import reload as _reload

                    project_root = str(Path(__file__).parent)
                    if project_root not in sys.path:
                        sys.path.append(project_root)

                    import configuration_values
                    import main as main_module
                    _reload(configuration_values)
                    _reload(main_module)

                    logger.info(f"Executing scheduled scrape that was due at {next_run_for_log}")
                    new_rfps = main_module.process_and_email(send_main=True, send_debug=True)
                    logger.info(f"Scheduled scrape complete. Found {len(new_rfps)} new RFPs")
                except Exception:
                    logger.exception("Error during scheduled scrape")

        except Exception:
            logger.exception("Error in scheduler loop")

        await asyncio.sleep(60)

@app.delete("/schedule")
def clear_schedule():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    with engine.begin() as conn:
        # ensure singleton exists
        row = conn.execute(select(scrape_config).where(scrape_config.c.id == "singleton")).first()
        if not row:
            conn.execute(
                insert(scrape_config).values(
                    id="singleton",
                    enabled=False,
                    interval_hours=24.0,
                    next_run_at=None,
                    last_run_at=None,
                    created_at=now_utc,
                    updated_at=now_utc,
                )
            )
        else:
            conn.execute(
                text("""
                    UPDATE scrape_config
                    SET enabled = false,
                        next_run_at = NULL,
                        last_run_at = NULL,
                        updated_at = :updated_at
                    WHERE id = 'singleton'
                """),
                {"updated_at": now_utc},
            )

        row2 = conn.execute(text("SELECT enabled, interval_hours, next_run_at, last_run_at FROM scrape_config WHERE id = 'singleton'")).first()
        m = row2._mapping
        return {
            "enabled": bool(m.get("enabled")),
            "interval_hours": float(m.get("interval_hours")) if m.get("interval_hours") is not None else None,
            "next_run_at": m.get("next_run_at").isoformat() if m.get("next_run_at") else None,
            "last_run_at": m.get("last_run_at").isoformat() if m.get("last_run_at") else None,
        }
