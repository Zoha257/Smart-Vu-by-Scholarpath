"""
app/core/security.py

Defense-in-depth admin-key check (Section 17.2). This is NOT the primary
control — the primary control is that this application is never bound to a
public network interface (Section 5.7.2, 18.5). This header check exists so
that even someone who reaches this process over the private network (e.g. a
misconfigured SSH tunnel, or another process on the same private LAN) still
needs a shared secret to call any route.
"""
from fastapi import Header, HTTPException, status

from app.core.config import get_settings

settings = get_settings()


async def require_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")) -> None:
    """
    FastAPI dependency. Attach to every admin router with:
        router = APIRouter(dependencies=[Depends(require_admin_key)])
    """
    if x_admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-Key header.",
        )
