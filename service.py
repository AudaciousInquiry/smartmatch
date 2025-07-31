from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import datetime
import logging

from main import main, process_and_email

app = FastAPI(title="SmartMatch Service")
logger = logging.getLogger("uvicorn.error")
scheduler = AsyncIOScheduler()
scheduler.add_job(
    func=lambda: _run_and_log(),
    trigger="interval",
    hours=24,
    next_run_time=datetime.datetime.now()
)

def _run_and_log():
    try:
        new = process_and_email(send_main=False, send_debug=True)
        logger.info(f"Scheduled run completed, {len(new)} new RFPs.")
    except Exception:
        logger.exception("Scheduled run failed")


@app.on_event("startup")
async def startup_event():
    scheduler.start()
    logger.info("Scheduler started.")

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()
    logger.info("Scheduler stopped.")

@app.post("/scrape")
async def scrape_now():
    main()
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat()}
