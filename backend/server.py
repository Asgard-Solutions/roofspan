import os
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy import select

from db import engine, SessionLocal
from models import User
from core import hash_password, verify_password
from migrations_runner import run_migrations
from routers import auth, users, audit, integrations, settings, territories, properties, imports, leads
from routers import customers, inspections, estimates, quotes, invoices, jobs
from routers import operations, purchasing, cron, admin_ops, mobile, licensing as licensing_router
from licensing import config as licensing_config, service as licensing_service
from licensing.middleware import SubscriptionGuardMiddleware
from control_plane.router import router as control_plane_router
from control_plane.service import init_control_plane

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("roofspan")

app = FastAPI(title="RoofSpan Office API", version="1.0.0")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "roofspan-office", "database": "postgresql"}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(audit.router)
app.include_router(integrations.router)
app.include_router(settings.router)
app.include_router(territories.router)
app.include_router(properties.router)
app.include_router(imports.router)
app.include_router(leads.router)
app.include_router(customers.router)
app.include_router(inspections.router)
app.include_router(estimates.router)
app.include_router(quotes.router)
app.include_router(invoices.router)
app.include_router(jobs.router)
app.include_router(operations.router)
app.include_router(purchasing.router)
app.include_router(cron.router)
app.include_router(admin_ops.router)
app.include_router(mobile.router)
app.include_router(licensing_router.router)
if licensing_config.LICENSING_MODE == "dev":
    from routers import licensing_dev
    app.include_router(licensing_dev.router)
app.include_router(control_plane_router)

# Guard business workflows when the subscription is not ACTIVE/GRACE. Added before CORS so CORS
# remains the outermost middleware (guard 403 responses still receive CORS headers).
app.add_middleware(SubscriptionGuardMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


async def seed_owner():
    email = os.environ.get("ADMIN_EMAIL", "").lower().strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    name = os.environ.get("ADMIN_NAME", "Owner")
    if not email or not password:
        logger.warning("ADMIN_EMAIL/ADMIN_PASSWORD not set; skipping owner seed")
        return
    async with SessionLocal() as db:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is None:
            db.add(User(email=email, full_name=name, password_hash=hash_password(password), role="owner", is_active=True))
            await db.commit()
            logger.info("Seeded owner account: %s", email)
        elif not verify_password(password, existing.password_hash):
            existing.password_hash = hash_password(password)
            await db.commit()
            logger.info("Updated owner password: %s", email)


@app.on_event("startup")
async def on_startup():
    # Migration-driven schema: Alembic is the single authoritative schema path (no create_all,
    # no manual SQL). Fresh DB builds from full history; existing DB migrates forward non-destructively.
    await asyncio.to_thread(run_migrations)
    await seed_owner()
    async with SessionLocal() as db:
        await licensing_service.bootstrap(db)
    try:
        await init_control_plane()
    except Exception as e:
        logger.warning("Control Plane init skipped/failed (non-fatal for the local installation): %s", e)
    logger.info("RoofSpan Office backend ready")


@app.on_event("shutdown")
async def on_shutdown():
    await engine.dispose()
