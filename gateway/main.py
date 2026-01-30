"""A2A Gateway - Main FastAPI Application.

This gateway provides:
- Agent discovery via UC connections ending with '-a2a'
- Authorization via UC connection access control
- Proxy to downstream A2A agents with SSE streaming support
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from config import settings
from services import get_proxy_service
from routes import health_router, agents_router

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    yield

    logger.info("Shutting down...")
    # Close the proxy service HTTP client
    proxy_service = get_proxy_service()
    await proxy_service.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="A2A Gateway for Databricks - Agent Discovery and Proxying",
    docs_url=None,  # Disable default docs, we'll create custom one
    redoc_url="/redoc",
    lifespan=lifespan
)


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """Custom Swagger UI that includes credentials with requests."""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{settings.app_name} - Swagger UI",
        swagger_ui_parameters={
            "withCredentials": True,  # Include cookies/credentials with requests
            "persistAuthorization": True,
        }
    )

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_timing(request: Request, call_next):
    """Add request timing header."""
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    response.headers["X-Process-Time"] = f"{duration:.3f}s"
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with proper JSON response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc) if settings.debug else None}
    )


# Include routers
app.include_router(health_router)
app.include_router(agents_router)


# Custom OpenAPI schema with security configuration
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=settings.app_name,
        version=settings.app_version,
        description="""
## A2A Gateway for Databricks

This gateway discovers and proxies to A2A-compliant agents registered via Unity Catalog connections.

### Authentication

**When deployed as a Databricks App:** Authentication is handled automatically via Databricks OAuth.
Your identity is passed via the `x-forwarded-email` header by the Databricks Apps proxy.
Simply access this Swagger UI while logged into your Databricks workspace.

**When calling via API/curl:** Include your Databricks OAuth token in the Authorization header:
```
Authorization: Bearer <your-databricks-token>
```

### Agent Access Control

Agents are filtered by Unity Catalog connection permissions. You will only see and be able to
access agents where you have `USE_CONNECTION` privilege on the corresponding UC connection.
""",
        routes=app.routes,
    )

    # Add security scheme for external API calls
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "description": "Databricks OAuth token (for API/curl access)"
        }
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# =============================================================================
# Local Development
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
