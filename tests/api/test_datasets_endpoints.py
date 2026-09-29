"""Dataset endpoints where no data exists: wiring, request shape, honesty.

The API test suite runs against an unreachable PostgreSQL server on
purpose - this suite has to be able to report "no database" rather than be
handed one. So what is proved here is everything that needs no rows:

* the three routes exist, under ``/api/v1`` and nowhere else, and nothing
  on the dataset surface is a verb other than ``GET``;
* the published schema declares the same fields the contracts do;
* the request rules that need no data: a timestamp must carry its own
  offset, an inverted window is a mistake rather than an empty answer,
  and a page size is bounded;
* a database that cannot be reached is reported as a failure, never as an
  empty directory. "There are no datasets" and "I could not read the
  manifest" are different answers, and only the first one may look like a
  success.

What needs real rows - provenance, stored bars, paging, refusals - lives
in ``tests/integration/test_datasets_http.py``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROBLEM_JSON = "application/problem+json"

DATASET_ROUTES = (
    "/api/v1/datasets",
    "/api/v1/datasets/{name}/bars",
    "/api/v1/datasets/{name}",
)


@pytest.fixture
def lenient_client(app: FastAPI) -> Iterator[TestClient]:
    """The same application, with server errors answered rather than raised.

    ``TestClient`` re-raises by default, which is right for a test whose
    subject is the handler. Here the subject is the *answer* a client gets
    when the database is unreachable, so the exception has to arrive as a
    response to be judged.
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.mark.unit
def test_the_dataset_routes_exist_only_in_the_versioned_surface(app: FastAPI) -> None:
    paths = list(app.openapi()["paths"])

    for route in DATASET_ROUTES:
        assert route in paths, f"{route} missing from the OpenAPI schema"

    # Read-only research surface: no alias (a probe has no business listing
    # datasets) and no second spelling for it to drift out of sync with.
    for unversioned in ("/datasets", "/datasets/{name}", "/datasets/{name}/bars"):
        assert unversioned not in paths, f"{unversioned} must not exist unversioned"


@pytest.mark.unit
def test_the_bars_route_is_registered_before_the_detail_route(app: FastAPI) -> None:
    """Both routes take a `{name:path}` capture; the order decides what matches.

    Registered the other way round, ``GET /datasets/anything/bars`` would
    be read as the detail of a dataset called ``anything/bars`` and would
    404 instead of serving bars. The assertion exists so the comment in
    the router cannot quietly stop being true.
    """
    paths = list(app.openapi()["paths"])

    assert paths.index("/api/v1/datasets/{name}/bars") < paths.index("/api/v1/datasets/{name}")


@pytest.mark.unit
def test_the_dataset_surface_serves_no_writing_verb(client: TestClient) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = client.request(method, "/api/v1/datasets")
        assert response.status_code == 405, f"{method} must not be answerable"
        assert response.headers["content-type"].startswith(PROBLEM_JSON)


@pytest.mark.unit
def test_the_published_schema_declares_the_contract_fields(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert set(schemas["DatasetSummary"]["properties"]) == {
        "name",
        "instrument",
        "timeframe",
        "quality_status",
        "version",
        "storage_path",
        "source",
        "acquired_at",
        "row_count",
        "updated_at",
    }
    assert set(schemas["BarPoint"]["properties"]) == {
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }


@pytest.mark.unit
def test_a_timestamp_without_an_offset_is_refused(client: TestClient) -> None:
    """Refusing beats guessing: local time would shift the window silently.

    The check runs before anything touches the database, so this holds
    even on a suite that has none.
    """
    response = client.get(
        "/api/v1/datasets/kraken.xbtusd.1h/bars",
        params={"start": "2026-09-01T00:00:00"},
    )

    assert response.status_code == 422
    body = response.json()
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert body["title"] == "Unprocessable Content"
    assert "no UTC offset" in body["detail"]


@pytest.mark.unit
def test_an_inverted_window_is_refused(client: TestClient) -> None:
    response = client.get(
        "/api/v1/datasets/kraken.xbtusd.1h/bars",
        params={"start": "2026-09-02T00:00:00+00:00", "end": "2026-09-01T00:00:00+00:00"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["title"] == "Unprocessable Content"
    assert "inverted window" in body["detail"]


@pytest.mark.unit
def test_the_page_size_is_bounded_by_the_router(client: TestClient) -> None:
    for limit in ("0", "5001", "-1"):
        response = client.get(
            "/api/v1/datasets/kraken.xbtusd.1h/bars",
            params={"limit": limit},
        )
        assert response.status_code == 422, f"limit={limit} should be refused"
        body = response.json()
        assert body["title"] == "Request validation failed"
        # The submitted value is not echoed: a query string can carry
        # anything, and the error body is not the place to reflect it.
        assert limit not in str(body.get("errors"))


@pytest.mark.unit
def test_an_unreachable_database_is_never_an_empty_directory(
    lenient_client: TestClient,
) -> None:
    """The honest-answer test for this suite.

    The manifest cannot be read here, so the endpoint must fail loudly.
    A ``200`` with ``{"datasets": []}`` would be indistinguishable from a
    platform that has ingested nothing, and would turn an outage into a
    finding.
    """
    response = lenient_client.get("/api/v1/datasets")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    payload = response.json()
    assert payload["title"] == "Internal Server Error"
    assert "datasets" not in payload


@pytest.mark.unit
def test_an_unreachable_database_is_never_an_empty_bars_page(
    lenient_client: TestClient,
) -> None:
    response = lenient_client.get("/api/v1/datasets/kraken.xbtusd.1h/bars")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert "bars" not in response.json()
