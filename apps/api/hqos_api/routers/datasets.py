"""Dataset endpoints: the directory, one dataset, and its stored bars.

================================================================  ==========================
``GET /api/v1/datasets``                                          every dataset, with provenance
``GET /api/v1/datasets/{name}```                                  one dataset and its acquisition history
``GET /api/v1/datasets/{name}/bars``                              one page of stored bars
================================================================  ==========================

This layer parses, delegates and maps — it never decides. Whether a name
exists and whether an artefact is readable are decided in
:mod:`hqos_api.services.datasets`; the router's own judgements are the
shape of the request: that a timestamp must carry its own offset, that an
inverted window is a mistake rather than an empty answer, and which
status each failure becomes.

**Read-only and unauthenticated, deliberately.** ``docs/architecture/
backend.md`` section 6 requires authentication for endpoints that expose
or act on an account, a session, a strategy, a position or an order, and
a dataset is none of those: it is public market data plus the record of
where it came from. The API still binds to loopback behind an explicit
CORS allow-list, and nothing here writes. If a future phase publishes
research data beyond that boundary, this is the router that grows a
session dependency.

Two request rules are visible from the outside and are asserted by tests:

* **a timestamp without a UTC offset is refused.** Guessing local time
  would shift a window by the machine's offset while every line of the
  response still looked correct; the CLI refuses the same thing for the
  same reason.
* **an inverted window is refused too.** Otherwise a caller's mistake
  and a genuinely empty range would both answer ``returned: 0``, and the
  response could no longer tell them apart.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status

from harsh_quant_os.config import Settings
from harsh_quant_os.contracts.datasets import (
    DatasetBarsResponse,
    DatasetDetailResponse,
    DatasetListResponse,
)
from hqos_api.dependencies import get_session_factory, get_store_root
from hqos_api.services.datasets import (
    DEFAULT_BARS_LIMIT,
    MAX_BARS_LIMIT,
    DatasetNotFound,
    DatasetNotStored,
    load_bars,
    load_dataset_detail,
    load_datasets,
)

_PROBLEM = "application/problem+json"


def _problem(description: str) -> dict[str, object]:
    return {"description": description, "content": {_PROBLEM: {"schema": {"type": "object"}}}}


_BARS_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: _problem("No dataset is registered under that name."),
    status.HTTP_409_CONFLICT: _problem(
        "The dataset is registered but its artefact cannot be served: it was never "
        "stored, its manifest row is incomplete, its path leaves the store, or the "
        "file is no longer on disk."
    ),
    status.HTTP_422_UNPROCESSABLE_CONTENT: _problem(
        "A bound is not an ISO 8601 instant, carries no UTC offset, points back "
        "before the window's start, or asks for more than the page size allows."
    ),
}

_DETAIL_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: _problem("No dataset is registered under that name."),
}


def _instant(value: datetime | None, field: str) -> datetime | None:
    """Normalise one query bound to UTC, or refuse it.

    A naive timestamp means local time, and a window shifted by the
    machine's offset would return real bars for the wrong hours — every
    line of it plausible, none of it what was asked for. Refusing beats
    guessing.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} carries no UTC offset; write it as 2026-01-01T00:00:00+00:00",
        )
    return value.astimezone(UTC)


def _check_window(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end must be after start; an inverted window is a mistake, not an empty range",
        )


def create_datasets_router(settings: Settings) -> APIRouter:
    """Build a router bound to one explicit ``Settings`` instance.

    It reads nothing from ``settings`` yet — it is accepted for the same
    reason every router factory accepts it, so that a router which later
    needs configuration changes in the same shape as its neighbours.
    """
    _ = settings
    router = APIRouter(tags=["datasets"])

    @router.get(
        "/datasets",
        response_model=DatasetListResponse,
        summary="List datasets",
        description=(
            "Every dataset in the manifest, ordered by name, each with its most "
            "recent acquisition: where the data came from, when, its checksum and "
            "its row count. Fields that were never recorded come back as `null` "
            "rather than as a number that would claim otherwise. An empty list "
            "means nothing has been ingested yet."
        ),
    )
    async def datasets(request: Request) -> DatasetListResponse:
        return await load_datasets(get_session_factory(request))

    # Registered before the detail route: Starlette matches in definition
    # order, and ``{name:path}`` on the detail route would otherwise
    # swallow ``.../bars`` as part of a dataset name.
    @router.get(
        "/datasets/{name:path}/bars",
        response_model=DatasetBarsResponse,
        responses=_BARS_RESPONSES,
        summary="Read a page of stored bars",
        description=(
            "A page of OHLCV read back from the stored artefact, tagged with the "
            "dataset version, timeframe, quality status and source they were read "
            "from — that tag is what makes any figure drawn from this response "
            "traceable. Bounds are inclusive and must carry a UTC offset; "
            "`cursor` is exclusive and takes `next_cursor` from the previous page. "
            "Bars are returned exactly as stored: never resampled, interpolated or "
            "filled in. `data/` is workspace state, so a manifest row whose file "
            "has been removed is reported as a conflict rather than as a short "
            "series."
        ),
    )
    async def dataset_bars(
        name: str,
        request: Request,
        start: datetime | None = Query(
            default=None, description="Inclusive lower bound, ISO 8601 with a UTC offset."
        ),
        end: datetime | None = Query(
            default=None, description="Inclusive upper bound, ISO 8601 with a UTC offset."
        ),
        cursor: datetime | None = Query(
            default=None,
            description=(
                "Exclusive lower bound: the timestamp of the last bar already "
                "held, taken from the previous page's `next_cursor`."
            ),
        ),
        limit: int = Query(
            default=DEFAULT_BARS_LIMIT,
            ge=1,
            le=MAX_BARS_LIMIT,
            description="Page size in bars.",
        ),
    ) -> DatasetBarsResponse:
        lower = _instant(start, "start")
        upper = _instant(end, "end")
        after = _instant(cursor, "cursor")
        _check_window(lower, upper)
        try:
            return await load_bars(
                get_session_factory(request),
                get_store_root(request),
                name=name,
                start=lower,
                end=upper,
                cursor=after,
                limit=limit,
            )
        except DatasetNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
        except DatasetNotStored as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    @router.get(
        "/datasets/{name:path}",
        response_model=DatasetDetailResponse,
        responses=_DETAIL_RESPONSES,
        summary="Describe one dataset",
        description=(
            "The dataset's manifest row plus every acquisition recorded against "
            "it, newest first. Provenance is append-only, so a re-ingest appears "
            "as an additional entry rather than a revision of an earlier one."
        ),
    )
    async def dataset_detail(name: str, request: Request) -> DatasetDetailResponse:
        try:
            return await load_dataset_detail(get_session_factory(request), name)
        except DatasetNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None

    return router
