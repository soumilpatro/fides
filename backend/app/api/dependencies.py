"""Reusable ordinary access authentication, separate from logout-only recognition."""

from typing import Annotated

from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.auth import authorization_header, bearer, get_auth_service
from app.auth.sessions import Principal


async def require_principal(
    request: Request,
    service=Depends(get_auth_service),
    _bearer: Annotated[object, Depends(bearer)] = None,
) -> Principal:
    """Resolve only from the current unexpired access hash and ACTIVE stored User.

    Mutation services must revalidate this principal under their User lock; an
    earlier dependency result must not survive a rotation/revocation race.
    """
    return await run_in_threadpool(service.session_service.resolve, authorization_header(request))
