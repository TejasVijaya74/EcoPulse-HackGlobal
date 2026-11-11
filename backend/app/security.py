import hmac

from fastapi import HTTPException, Request

from app.config import API_ACCESS_TOKEN

MIN_API_TOKEN_LENGTH = 32


def require_api_token(request: Request) -> None:
    if len(API_ACCESS_TOKEN) < MIN_API_TOKEN_LENGTH:
        raise HTTPException(
            status_code=503,
            detail="Protected API operations are not configured.",
        )

    scheme, separator, supplied_token = request.headers.get("authorization", "").partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(
            API_ACCESS_TOKEN.encode("utf-8"),
            supplied_token.strip().encode("utf-8"),
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="A valid bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
