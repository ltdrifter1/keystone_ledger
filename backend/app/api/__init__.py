from fastapi import APIRouter

from app.api import (
    attachments,
    close_pack,
    dashboard,
    dimensions,
    engagement,
    feeds,
    imports,
    journals,
    reconciliations,
    reports,
    rules,
    session,
    transactions,
    views,
    working_papers,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(dashboard.router, tags=["dashboard"])
api_router.include_router(session.router, tags=["session"])
api_router.include_router(engagement.router, tags=["engagement"])
api_router.include_router(views.router, tags=["views"])
api_router.include_router(close_pack.router, tags=["close-pack"])
api_router.include_router(feeds.router, tags=["bank-feeds"])
api_router.include_router(transactions.router, tags=["transactions"])
api_router.include_router(journals.router, tags=["journals"])
api_router.include_router(attachments.router, tags=["attachments"])
api_router.include_router(imports.router, tags=["imports"])
api_router.include_router(reconciliations.router, tags=["reconciliations"])
api_router.include_router(reports.router, tags=["reports"])
api_router.include_router(working_papers.router, tags=["working-papers"])
api_router.include_router(dimensions.router, tags=["dimensions"])
api_router.include_router(rules.router, tags=["rules"])
