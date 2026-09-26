from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class NotFoundError(Exception):
    def __init__(self, resource: str, id: int) -> None:
        self.resource = resource
        self.id = id
        super().__init__(f"{resource} with id={id} not found")


class ConflictError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class ValidationError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)


# ── FastAPI exception handlers ────────────────────────────────────────────────

async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc), "resource": exc.resource, "id": exc.id},
    )


async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": str(exc)},
    )
