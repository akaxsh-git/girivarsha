"""
Shared helper for endpoints whose *contract* (path, method, response shape)
is defined now per docs/API_Documentation.md, but whose implementation lands
in a later phase. Returning honest 501s here (instead of hard-coded fake
data) is deliberate — see problem-statement item 52 ("do not hard-code
changing predictions into the frontend").
"""
from fastapi import HTTPException


def not_implemented(endpoint: str, planned_phase: str) -> None:
    raise HTTPException(
        status_code=501,
        detail={
            "endpoint": endpoint,
            "status": "not_implemented",
            "planned_phase": planned_phase,
            "message": (
                "This endpoint's contract is defined but not yet backed by real "
                "logic. See docs/API_Documentation.md and README.md for build status."
            ),
        },
    )
