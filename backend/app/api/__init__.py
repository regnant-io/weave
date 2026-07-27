from fastapi import APIRouter

from . import (admin, analysis, auth, channels, citations, config, datasets, library,
               messages, projects)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(datasets.router, tags=["datasets"])
api_router.include_router(messages.router, tags=["messages"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(library.router, prefix="/library", tags=["library"])
api_router.include_router(citations.router, prefix="/citations", tags=["citations"])
api_router.include_router(config.router, tags=["config"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(channels.router, prefix="/channels", tags=["channels"])

__all__ = ["api_router"]
