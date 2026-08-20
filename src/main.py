import secrets

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config import get_settings
from routes import accounts_router, cart_router, movies_router, orders_router

settings = get_settings()


app = FastAPI(
    title="Online Cinema API",
    description=(
        "Backend for an online cinema.\n\n"
        "Accounts are confirmed by email before they can sign in. Users browse "
        "a movie catalog, collect movies in a cart and turn that cart into an "
        "order. Moderators maintain the catalog; admins manage accounts."
    ),
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

API_PREFIX = "/api/v1"

security = HTTPBasic()


def require_docs_access(
    credentials: HTTPBasicCredentials = Depends(security),
) -> str:
    correct_user = secrets.compare_digest(credentials.username, settings.DOCS_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, settings.DOCS_PASSWORD)

    if not (correct_user and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid documentation credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@app.get("/openapi.json", include_in_schema=False)
async def openapi_schema(_: str = Depends(require_docs_access)) -> dict:
    return get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )


@app.get("/docs", include_in_schema=False)
async def swagger_ui(_: str = Depends(require_docs_access)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} — Swagger")


@app.get("/redoc", include_in_schema=False)
async def redoc_ui(_: str = Depends(require_docs_access)):
    return get_redoc_html(openapi_url="/openapi.json", title=f"{app.title} — ReDoc")


@app.get("/health/", tags=["service"], summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(accounts_router, prefix=f"{API_PREFIX}/accounts", tags=["accounts"])
app.include_router(movies_router, prefix=f"{API_PREFIX}/cinema", tags=["cinema"])
app.include_router(cart_router, prefix=f"{API_PREFIX}/shop", tags=["cart"])
app.include_router(orders_router, prefix=f"{API_PREFIX}/shop", tags=["orders"])
