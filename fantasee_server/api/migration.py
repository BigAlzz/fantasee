"""Migration readiness API."""

from fastapi import APIRouter

from fantasee_server.migration import migration_readiness


router = APIRouter(tags=["migration"])


@router.get("/api/migration/readiness")
def get_migration_readiness():
    return migration_readiness()
