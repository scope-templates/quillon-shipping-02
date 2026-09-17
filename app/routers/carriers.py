"""The four carriers we route to, and what each of them sells."""

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.auth import Caller, caller
from app.db import get_conn
from app.records import carriers_out
from app.schemas import Carriers, problem_responses

router = APIRouter(prefix="/v1", tags=["Carriers"])


@router.get(
    "/carriers",
    response_model=Carriers,
    summary="The carriers and their services",
    operation_id="list_carriers",
    responses=problem_responses(),
)
def list_carriers(
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    """Service names for the whole account. Which of them will take a given parcel is a quote.

    We add and drop carriers from time to time; read this rather than hard-coding the four.
    """
    return {"data": carriers_out(conn)}
