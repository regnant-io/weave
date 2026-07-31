"""The collaborative canvas — one document, edited live by both parties."""
from .service import (AnchorNotFound, CanvasConflict, CanvasService,
                      get_canvas_service)

__all__ = ["AnchorNotFound", "CanvasConflict", "CanvasService", "get_canvas_service"]
