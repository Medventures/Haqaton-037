import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()
logging.basicConfig(level=logging.INFO)

from db import create_db_and_tables  # noqa: E402
from routers import auth, cases, parent, plans  # noqa: E402
from routers import services as services_router  # noqa: E402
from services import catalog  # noqa: E402, F401  load the catalog at startup so bad data fails fast


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_db_and_tables()
    yield


app = FastAPI(title="AqylRoute AI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,  # e.g. Vercel preview deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(plans.router)
app.include_router(parent.router)
app.include_router(services_router.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
