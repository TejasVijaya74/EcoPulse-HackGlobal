import hmac

from fastapi import HTTPException, Request

from app.config import API_ACCESS_TOKEN, PUBLIC_DEMO_MODE

MIN_API_TOKEN_LENGTH = 32


def is_valid_api_token(value: str | None) -> bool:
    if len(API_ACCESS_TOKEN) < MIN_API_TOKEN_LENGTH or not isinstance(value, str):
        return False

    return bool(
        value
        and hmac.compare_digest(
            API_ACCESS_TOKEN.encode("utf-8"),
            value.encode("utf-8"),
        )
    )


def _authorization_token(request: Request) -> str | None:
    scheme, separator, supplied_token = request.headers.get("authorization", "").partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    return supplied_token.strip()


def has_valid_api_token(request: Request) -> bool:
    return is_valid_api_token(_authorization_token(request))


def public_demo_mode_enabled() -> bool:
    return PUBLIC_DEMO_MODE


def require_api_token(request: Request) -> None:
    if len(API_ACCESS_TOKEN) < MIN_API_TOKEN_LENGTH:
        raise HTTPException(
            status_code=503,
            detail="Protected API operations are not configured.",
        )
    if not has_valid_api_token(request):
        raise HTTPException(
            status_code=401,
            detail="A valid bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_public_demo_or_api_token(request: Request) -> None:
    if public_demo_mode_enabled():
        return
    require_api_token(request)
