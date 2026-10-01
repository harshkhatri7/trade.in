"""Promotion workflow: the gates are checked, not promised.

Golden flow, hand-traced against anti-overfitting §3:

1. ``register`` opens a record at ``candidates`` with exactly one
   ``exploratory_run`` entry and one history line from
   ``unregistered`` — the §3 floor for a candidate.
2. Promoting immediately is refused with all four required kinds
   named: held-out, walk-forward, sensitivity, critique.
3. A critique recorded by the candidate's own author is refused at
   append time, at promotion time, and at load time (§2.10's
   independence, three layers).
4. With all four kinds recorded by ``auditor``, promotion succeeds:
   history reads ``unregistered -> candidates -> validated``.
5. ``rejected`` is terminal with its reason (§2.9), validated
   archives but never rewrites as never-tried, and no stage named
   ``live`` exists anywhere in the machine.
6. A transition moves the file: write the new stage's file first,
   remove the old one after, so a failed write loses nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harsh_quant_os.backtesting import (
    BacktestError,
    Evidence,
    PromotionRecord,
    Transition,
    add_evidence,
    archive,
    iter_records,
    load_record,
    promote_to_validated,
    record_from_json,
    record_to_json,
    register,
    reject,
    save_record,
)

pytestmark = pytest.mark.backtesting

_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)

_REQUIRED = ("held_out", "walk_forward", "sensitivity", "critique")


def _candidate() -> PromotionRecord:
    return register(
        slug="band-v2",
        hypothesis="enter on a 1% band, exit on a 0.5% retrace",
        author="quant",
        at=_AT,
        reference="run-0001",
        detail="exploratory run on the pinned 1m dataset",
    )


def _fully_evidenced(record: PromotionRecord) -> PromotionRecord:
    for kind in _REQUIRED:
        record = add_evidence(
            record,
            kind=kind,
            reference=f"ref-{kind}",
            detail=f"the recorded {kind} entry",
            recorded_by="auditor",
            at=_LATER,
        )
    return record


def _validated() -> PromotionRecord:
    return promote_to_validated(
        _fully_evidenced(_candidate()),
        actor="auditor",
        reason="section 3 gates met",
        at=_LATER,
    )


def _payload(record: PromotionRecord) -> dict[str, object]:
    parsed: object = json.loads(record_to_json(record))
    if not isinstance(parsed, dict):
        raise AssertionError("a record serialises to a JSON object")
    return parsed


# ---------------------------------------------------------------------------
# Registration and the §3 gate
# ---------------------------------------------------------------------------


def test_registration_opens_with_the_exploratory_run() -> None:
    record = _candidate()

    assert record.stage == "candidates"
    assert [entry.kind for entry in record.evidence] == ["exploratory_run"]
    assert record.evidence[0].reference == "run-0001"
    assert len(record.history) == 1
    assert record.history[0].from_stage == "unregistered"
    assert record.history[0].to_stage == "candidates"
    assert record.missing_for_validated == _REQUIRED
    assert "never measured results" in record.note


def test_promotion_without_the_section_3_evidence_names_every_gap() -> None:
    with pytest.raises(BacktestError) as excinfo:
        promote_to_validated(_candidate(), actor="auditor", reason="gates met", at=_LATER)

    message = str(excinfo.value)
    assert "cannot be marked validated" in message
    for kind in _REQUIRED:
        assert kind in message
    assert "there is no partial pass" in message


def test_the_gap_list_names_exactly_what_is_still_missing() -> None:
    record = add_evidence(
        _candidate(),
        kind="held_out",
        reference="ref-held-out",
        detail="the held-out evaluation",
        recorded_by="auditor",
        at=_LATER,
    )
    assert record.missing_for_validated == (
        "walk_forward",
        "sensitivity",
        "critique",
    )
    with pytest.raises(BacktestError) as excinfo:
        promote_to_validated(record, actor="auditor", reason="gates met", at=_LATER)

    message = str(excinfo.value)
    assert "(walk_forward, sensitivity, critique)" in message
    assert "held_out," not in message


def test_a_critique_never_from_the_authors_own_hand() -> None:
    record = _candidate()

    with pytest.raises(BacktestError, match="someone other than"):
        add_evidence(
            record,
            kind="critique",
            reference="ref-critique",
            detail="the author's own critique",
            recorded_by="quant",
            at=_LATER,
        )

    # A hand-written candidates record cannot smuggle one in either:
    # loading accepts it (its stage is only candidates), and the
    # promotion gate refuses it there.
    payload = _payload(_fully_evidenced(record))
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    for entry in evidence:
        if entry.get("kind") == "critique":
            entry["recorded_by"] = "quant"
    tampered = record_from_json(json.dumps(payload))
    with pytest.raises(BacktestError, match="someone other than"):
        promote_to_validated(tampered, actor="auditor", reason="gates met", at=_LATER)


def test_promotion_succeeds_once_everything_is_recorded() -> None:
    promoted = _validated()

    assert promoted.stage == "validated"
    assert promoted.missing_for_validated == ()
    assert len(promoted.history) == 2
    move = promoted.history[1]
    assert (move.from_stage, move.to_stage) == ("candidates", "validated")
    assert move.reason == "section 3 gates met"

    with pytest.raises(BacktestError, match="only a candidate"):
        promote_to_validated(promoted, actor="auditor", reason="again", at=_LATER)


# ---------------------------------------------------------------------------
# Rejection, archiving, and the stages that do not exist
# ---------------------------------------------------------------------------


def test_rejection_keeps_its_reason_visible() -> None:
    record = _candidate()

    with pytest.raises(BacktestError, match="true number of attempts"):
        reject(record, actor="quant", reason="   ", at=_LATER)

    rejected = reject(record, actor="quant", reason="regime test never traded", at=_LATER)
    assert rejected.stage == "rejected"
    assert rejected.history[-1].reason == "regime test never traded"

    # Rejected is terminal: no re-animation, no rewriting.
    with pytest.raises(BacktestError, match="stay in rejected"):
        archive(rejected, actor="quant", reason="tidying up", at=_LATER)
    with pytest.raises(BacktestError, match="keeps its evidence"):
        add_evidence(
            rejected,
            kind="critique",
            reference="ref-late",
            detail="too late",
            recorded_by="auditor",
            at=_LATER,
        )


def test_a_validated_strategy_is_archived_never_rewritten() -> None:
    promoted = _validated()

    with pytest.raises(BacktestError, match="never rewritten as never-tried"):
        reject(promoted, actor="quant", reason="changed my mind", at=_LATER)

    archived = archive(promoted, actor="quant", reason="superseded by band-v3", at=_LATER)
    assert archived.stage == "archived"
    assert archived.history[-1].reason == "superseded by band-v3"

    with pytest.raises(BacktestError, match="keeps its reason"):
        archive(_candidate(), actor="quant", reason="  ", at=_LATER)


def test_no_stage_named_live_exists() -> None:
    with pytest.raises(BacktestError, match="no live stage"):
        Transition(
            at=_LATER,
            actor="quant",
            from_stage="validated",
            to_stage="live",
            reason="wants it now",
        )


# ---------------------------------------------------------------------------
# Evidence and field refusals
# ---------------------------------------------------------------------------


def test_evidence_appends_once_and_only_while_the_stage_is_open() -> None:
    record = add_evidence(
        _candidate(),
        kind="held_out",
        reference="ref-held-out",
        detail="the held-out evaluation",
        recorded_by="auditor",
        at=_LATER,
    )

    with pytest.raises(BacktestError, match="append-only"):
        add_evidence(
            record,
            kind="held_out",
            reference="ref-held-out-again",
            detail="a second one",
            recorded_by="auditor",
            at=_LATER,
        )


def test_fields_that_cannot_be_named_or_ordered_are_refused() -> None:
    with pytest.raises(BacktestError, match="closed set"):
        Evidence(
            kind="made_up",
            reference="ref",
            detail="a kind outside the closed set",
            recorded_by="quant",
            recorded_at=_AT,
        )
    with pytest.raises(BacktestError, match="UTC offset"):
        Evidence(
            kind="held_out",
            reference="ref",
            detail="a naive instant",
            recorded_by="quant",
            recorded_at=datetime(2026, 10, 1, 12, 0),
        )
    with pytest.raises(BacktestError, match="valid slug"):
        register(
            slug="Band/V2",
            hypothesis="a slug that names a path",
            author="quant",
            at=_AT,
            reference="run-0001",
            detail="exploratory",
        )
    with pytest.raises(BacktestError, match="states something"):
        register(
            slug="x",
            hypothesis="   ",
            author="quant",
            at=_AT,
            reference="run-0001",
            detail="exploratory",
        )
    with pytest.raises(BacktestError, match="one exploratory run"):
        PromotionRecord(
            slug="x",
            hypothesis="h",
            author="quant",
            stage="candidates",
            evidence=(),
            history=(),
        )


# ---------------------------------------------------------------------------
# JSON: round-trip, and records whose past could not have happened
# ---------------------------------------------------------------------------


def test_the_record_round_trips_and_rebuilds_byte_for_byte() -> None:
    record = _fully_evidenced(_candidate())

    text = record_to_json(record)
    assert record_from_json(text) == record
    assert record_to_json(record_from_json(text)) == text


def test_loading_refuses_a_foreign_or_future_layout() -> None:
    payload = _payload(_validated())
    payload["kind"] = "something_else"
    with pytest.raises(BacktestError, match="refusing to read it as one"):
        record_from_json(json.dumps(payload))

    payload = _payload(_validated())
    payload["record_version"] = 99
    with pytest.raises(BacktestError, match="refusing to guess its layout"):
        record_from_json(json.dumps(payload))

    payload = _payload(_validated())
    payload["stage"] = "live"
    with pytest.raises(BacktestError, match="no live stage"):
        record_from_json(json.dumps(payload))

    with pytest.raises(BacktestError, match="not valid JSON"):
        record_from_json("{not json")


def test_loading_refuses_a_history_that_could_not_have_happened() -> None:
    payload = _payload(_validated())
    history = payload["history"]
    assert isinstance(history, list)
    history[0]["to"] = "rejected"
    with pytest.raises(BacktestError, match="no path"):
        record_from_json(json.dumps(payload))

    payload = _payload(_validated())
    history = payload["history"]
    assert isinstance(history, list)
    payload["history"] = history[:-1]  # ends before the promotion it claims
    with pytest.raises(BacktestError, match="cannot reach"):
        record_from_json(json.dumps(payload))


def test_loading_refuses_a_validated_record_missing_the_gates() -> None:
    payload = _payload(_validated())
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    payload["evidence"] = [entry for entry in evidence if entry.get("kind") != "walk_forward"]
    with pytest.raises(BacktestError, match="product rule"):
        record_from_json(json.dumps(payload))


def test_loading_refuses_a_validated_record_on_a_self_critique() -> None:
    payload = _payload(_validated())
    evidence = payload["evidence"]
    assert isinstance(evidence, list)
    for entry in evidence:
        if entry.get("kind") == "critique":
            entry["recorded_by"] = "quant"
    with pytest.raises(BacktestError, match="authored it"):
        record_from_json(json.dumps(payload))


# ---------------------------------------------------------------------------
# Persistence: the stage move, one record per slug, listings that hide nothing
# ---------------------------------------------------------------------------


def test_a_transition_moves_the_file_and_one_slug_has_one_record(
    tmp_path: Path,
) -> None:
    record = _candidate()
    first = save_record(tmp_path, record)
    assert first == tmp_path / "candidates" / "band-v2.json"
    assert first.is_file()

    promoted = _validated()
    second = save_record(tmp_path, promoted)
    assert second == tmp_path / "validated" / "band-v2.json"
    assert second.is_file()
    assert not first.exists()  # written new, old removed after
    assert load_record(tmp_path, "band-v2") == promoted

    # Two copies cannot both be current.
    duplicate = tmp_path / "rejected" / "band-v2.json"
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_text(record_to_json(record), encoding="utf-8")
    with pytest.raises(BacktestError, match="one strategy has one record"):
        load_record(tmp_path, "band-v2")


def test_a_slug_that_names_a_path_is_refused_before_any_path_is_built(
    tmp_path: Path,
) -> None:
    with pytest.raises(BacktestError, match="valid slug"):
        load_record(tmp_path, "../evil")
    with pytest.raises(BacktestError, match="valid slug"):
        load_record(tmp_path, "two words")
    with pytest.raises(BacktestError, match="no record named"):
        load_record(tmp_path, "absent")


def test_listing_hides_nothing(tmp_path: Path) -> None:
    save_record(tmp_path, _candidate())
    save_record(tmp_path, _validated())
    # a second record so the stage order is visible:
    other = register(
        slug="alpha-first",
        hypothesis="another hypothesis",
        author="quant",
        at=_AT,
        reference="run-0002",
        detail="exploratory",
    )
    save_record(tmp_path, other)

    listed = [(record.stage, record.slug) for record in iter_records(tmp_path)]
    assert listed == [
        ("candidates", "alpha-first"),
        ("validated", "band-v2"),
    ]

    broken = tmp_path / "candidates" / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(BacktestError, match="valid JSON"):
        list(iter_records(tmp_path))

    # A record filed where its own stage disagrees raises too.
    broken.unlink()
    ghost = tmp_path / "candidates" / "band-v2.json"
    ghost.write_text(record_to_json(_validated()), encoding="utf-8")
    with pytest.raises(BacktestError, match="claiming another stage"):
        list(iter_records(tmp_path))
