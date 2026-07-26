from fastapi import APIRouter

from app.api import dashboard, dimensions, imports, reconciliations, reports, rules, transactions

api_router = APIRouter(prefix="/api")
api_router.include_router(dashboard.router, tags=["dashboard"])
api_router.include_router(transactions.router, tags=["transactions"])
api_router.include_router(imports.router, tags=["imports"])
api_router.include_router(reconciliations.router, tags=["reconciliations"])
api_router.include_router(reports.router, tags=["reports"])
api_router.include_router(dimensions.router, tags=["dimensions"])
api_router.include_router(rules.router, tags=["rules"])
