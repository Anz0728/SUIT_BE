from fastapi import APIRouter, HTTPException, status

from suit_backend.deps import CurrentUser

router = APIRouter(prefix="/recognition", tags=["recognition"])


def provider_not_configured() -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "PROVIDER_NOT_CONFIGURED",
            "message": "AI recognition provider is not configured. No media was stored.",
        },
    )


@router.post("/sign")
def recognize_sign(_: CurrentUser) -> None:
    """Reserved contract for the real sign-language inference adapter."""
    provider_not_configured()


@router.post("/speech")
def recognize_speech(_: CurrentUser) -> None:
    """Reserved contract for the real STT adapter."""
    provider_not_configured()

