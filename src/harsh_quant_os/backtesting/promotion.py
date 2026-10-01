"""The candidate / validated / rejected / archived promotion workflow.

Anti-overfitting §3 sets the gates::

    candidates/    a registered hypothesis and one exploratory run
    validated/     held-out test + walk-forward + sensitivity +
                   critique, all recorded
    live           everything above plus paper trading (Phase 10)
                   and human approval

ROADMAP Phase 7's exit criterion is the product rule this module
enforces: a strategy cannot be marked ``validated`` without
out-of-sample and walk-forward evidence attached.

Shape of the thing:

- Four stages, four directories. A record lives at
  ``strategies/<stage>/<slug>.json``; a transition moves it, and the
  move is write-new-then-remove-old so a failed write loses nothing.
- Evidence is a recorded *reference* — kind, what it was, who
  recorded it, when — never a measurement. Run manifests, reports
  and scores are artefacts of runs and stay outside version control;
  the record points at them by id, so nothing here can drift from a
  number it no longer owns, and nothing here invents one.
- Gates, not guidelines: promotion refuses while any of §3's four
  kinds is missing, refuses a critique recorded by the candidate's
  own author (§2.10's independence, checked rather than promised),
  and rejection and archiving each require a stated reason (§2.9 —
  rejected candidates keep their reasons so the true number of
  attempts stays visible).
- There is no live stage and no transition that reaches one: live
  consideration is Phase 10 plus human approval, deliberately
  outside this machine.
- History is append-only: every stage change is a ``Transition``,
  and loading replays the recorded history through the same rules —
  a record whose past could not have happened is refused, not read.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from harsh_quant_os.backtesting.errors import BacktestError

__all__ = [
    "EVIDENCE_KINDS",
    "RECORD_VERSION",
    "REQUIRED_FOR_VALIDATED",
    "STAGES",
    "Evidence",
    "PromotionRecord",
    "Transition",
    "add_evidence",
    "archive",
    "iter_records",
    "load_record",
    "promote_to_validated",
    "record_from_json",
    "record_to_json",
    "register",
    "reject",
    "save_record",
]

#: The four stages, in workflow order. There is deliberately no fifth.
STAGES = ("candidates", "validated", "rejected", "archived")

#: Every evidence kind that can be recorded, and the only ones.
EVIDENCE_KINDS = (
    "exploratory_run",
    "held_out",
    "walk_forward",
    "sensitivity",
    "critique",
)

#: What §3 demands before a record may sit at ``validated``.
REQUIRED_FOR_VALIDATED = ("held_out", "walk_forward", "sensitivity", "critique")

#: The JSON layout this build writes and is willing to read.
RECORD_VERSION = 1

#: Where every history begins — the state before registration.
_ORIGIN = "unregistered"

#: Legal transitions, replayed on load. Nothing reaches beyond the
#: four stages; nothing leaves ``rejected`` or ``archived``.
_LEGAL: dict[str, tuple[str, ...]] = {
    _ORIGIN: ("candidates",),
    "candidates": ("validated", "rejected", "archived"),
    "validated": ("archived",),
    "rejected": (),
    "archived": (),
}

#: Slugs become file names: lowercase, digits, single hyphens, and
#: nothing that could name a path instead of a record.
_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

_NOTE = (
    "A promotion record holds references and reasons, never measured "
    "results: run manifests and reports stay artefacts of runs, "
    "outside version control, and the record names them by id."
)


def _aware(value: object, where: str) -> datetime:
    """A timezone-aware ``datetime``, or a refusal naming ``where``."""
    if not isinstance(value, datetime):
        raise BacktestError(f"{where} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise BacktestError(
            f"{where} carries no UTC offset ({value.isoformat()}): a recorded "
            "instant without one cannot be ordered against another, and it is "
            "refused rather than assumed to be UTC"
        )
    return value


def _text(value: object, where: str) -> str:
    """A non-empty ``str`` from parsed JSON, or a refusal."""
    if not isinstance(value, str):
        raise BacktestError(f"{where} must be a string, got {type(value).__name__}")
    if not value.strip():
        raise BacktestError(f"{where} is empty: a recorded field states something")
    return value


def _slug_text(value: object, where: str) -> str:
    """A path-safe slug, or a refusal saying why it is not one."""
    slug = _text(value, where)
    if not _SLUG_PATTERN.fullmatch(slug):
        raise BacktestError(
            f"{where} is not a valid slug: {slug!r} — lowercase letters, digits "
            "and single hyphens only; a slug becomes a file name, and one that "
            "could name a path instead of a record is refused"
        )
    return slug


@dataclass(frozen=True, slots=True)
class Evidence:
    """One recorded piece of evidence — a reference, never a number.

    Attributes:
        kind: One of :data:`EVIDENCE_KINDS`.
        reference: How to find the artefact (run id, manifest hash,
            critique document id) — the artefact itself is not stored
            here.
        detail: What this entry was, in words.
        recorded_by: Who recorded it (an agent role or a person).
        recorded_at: When, timezone-aware.

    Raises:
        BacktestError: An unknown kind, an empty field, a reference
            carrying control characters, or a naive timestamp.
    """

    kind: str
    reference: str
    detail: str
    recorded_by: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        raw_kind: object = self.kind
        if not isinstance(raw_kind, str) or raw_kind not in EVIDENCE_KINDS:
            raise BacktestError(
                f"evidence kind must be one of {', '.join(EVIDENCE_KINDS)}, got "
                f"{self.kind!r}: the gate checks recorded kinds, so the kinds "
                "are a closed set"
            )
        _text(self.reference, "evidence reference")
        if any(ord(character) < 32 for character in self.reference):
            raise BacktestError(
                "an evidence reference stays on one line: control characters are refused"
            )
        _text(self.detail, "evidence detail")
        _text(self.recorded_by, "evidence recorded_by")
        _aware(self.recorded_at, "evidence recorded_at")


@dataclass(frozen=True, slots=True)
class Transition:
    """One append-only stage change.

    Attributes:
        at: When, timezone-aware.
        actor: Who made the change.
        from_stage: The stage left (``unregistered`` for
            registration).
        to_stage: The stage entered — one of :data:`STAGES`.
        reason: Why, always non-empty: every move states itself.

    Raises:
        BacktestError: An unknown stage, an empty actor or reason, a
            naive timestamp, or a move into ``unregistered``.
    """

    at: datetime
    actor: str
    from_stage: str
    to_stage: str
    reason: str

    def __post_init__(self) -> None:
        _aware(self.at, "transition at")
        _text(self.actor, "transition actor")
        raw_from: object = self.from_stage
        if not isinstance(raw_from, str) or raw_from not in (_ORIGIN, *STAGES):
            raise BacktestError(
                f"transition from_stage must be {_ORIGIN!r} or one of "
                f"{', '.join(STAGES)}, got {self.from_stage!r}"
            )
        raw_to: object = self.to_stage
        if not isinstance(raw_to, str) or raw_to not in STAGES:
            raise BacktestError(
                f"transition to_stage must be one of {', '.join(STAGES)}, got "
                f"{self.to_stage!r}: there is no other destination — in "
                "particular no live stage, which is Phase 10 plus human "
                "approval"
            )
        _text(self.reason, "transition reason")


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    """One strategy's promotion record: identity, evidence, history.

    Attributes:
        slug: File-safe identity (lowercase, digits, single hyphens).
        hypothesis: The registered hypothesis this candidate tests
            (§3: registration means a stated hypothesis, not a name).
        author: Who is accountable for the candidate — the floor for
            §2.10's independence: the critique must be recorded by
            someone else.
        stage: One of :data:`STAGES`.
        evidence: Append-only; opens with the exploratory run.
        history: Append-only; opens with the registration.

    Raises:
        BacktestError: An invalid slug or an empty identity field; an
        evidence list that is empty, opens with something other than
        the exploratory run, repeats a kind, or is not all
        ``Evidence``; a ``validated`` record missing any of §3's four
        required kinds or carrying a critique recorded by its own
        author; a history that is empty, does not chain, records an
        illegal move, or ends at a stage other than the record's
        stage.
    """

    slug: str
    hypothesis: str
    author: str
    stage: str
    evidence: tuple[Evidence, ...]
    history: tuple[Transition, ...]

    def __post_init__(self) -> None:
        _slug_text(self.slug, "record slug")
        _text(self.hypothesis, "record hypothesis")
        _text(self.author, "record author")
        raw_stage: object = self.stage
        if not isinstance(raw_stage, str) or raw_stage not in STAGES:
            raise BacktestError(
                f"record stage must be one of {', '.join(STAGES)}, got "
                f"{self.stage!r} — there is no live stage in this workflow"
            )

        raw_evidence: object = self.evidence
        if not isinstance(raw_evidence, tuple) or not raw_evidence:
            raise BacktestError(
                f"{self.slug} carries no evidence: a record begins with its "
                "one exploratory run (anti-overfitting §3)"
            )
        for item in raw_evidence:
            raw_item: object = item
            if not isinstance(raw_item, Evidence):
                raise BacktestError(
                    f"{self.slug}: every evidence entry must be an Evidence, "
                    f"got {type(raw_item).__name__}"
                )
        kinds = [entry.kind for entry in self.evidence]
        if kinds[0] != "exploratory_run":
            raise BacktestError(
                f"{self.slug} opens with {kinds[0]!r} evidence: a record opens "
                "with its exploratory run — the §3 floor for candidates"
            )
        if len(set(kinds)) != len(kinds):
            raise BacktestError(
                f"{self.slug} repeats an evidence kind: one entry per kind, "
                "append-only, so nothing can be quietly replaced"
            )

        if self.stage == "validated":
            missing = [kind for kind in REQUIRED_FOR_VALIDATED if kind not in kinds]
            if missing:
                raise BacktestError(
                    f"{self.slug} sits at validated without "
                    f"({', '.join(missing)}) recorded: the product rule is "
                    "that validated requires the held-out test, walk-forward, "
                    "sensitivity and critique all recorded (anti-overfitting "
                    "§3, ROADMAP phase 7), and it is checked on every load, "
                    "not only at promotion time"
                )
            critique = next(entry for entry in self.evidence if entry.kind == "critique")
            if critique.recorded_by == self.author:
                raise BacktestError(
                    f"{self.slug} sits at validated on a critique recorded by "
                    f"{self.author}, who authored it: §2.10's critique must be "
                    "recorded by someone other than the author, and the gate "
                    "checks it rather than trusts it"
                )

        raw_history: object = self.history
        if not isinstance(raw_history, tuple) or not raw_history:
            raise BacktestError(
                f"{self.slug} carries no history: every record opens with its registration"
            )
        replay = _ORIGIN
        for item in raw_history:
            raw_transition: object = item
            if not isinstance(raw_transition, Transition):
                raise BacktestError(
                    f"{self.slug}: every history entry must be a Transition, "
                    f"got {type(raw_transition).__name__}"
                )
            if raw_transition.from_stage != replay:
                raise BacktestError(
                    f"{self.slug}: history does not chain — an entry records "
                    f"{raw_transition.from_stage} -> {raw_transition.to_stage} "
                    f"where the previous move ended at {replay}"
                )
            if raw_transition.to_stage not in _LEGAL[replay]:
                raise BacktestError(
                    f"{self.slug}: history records {replay} -> "
                    f"{raw_transition.to_stage}, a move this workflow has no "
                    "path for"
                )
            replay = raw_transition.to_stage
        if replay != self.stage:
            raise BacktestError(
                f"{self.slug}: history ends at {replay} but the record says "
                f"stage {self.stage}: a record whose present it cannot reach "
                "is refused, not read"
            )

    @property
    def missing_for_validated(self) -> tuple[str, ...]:
        """The §3 kinds not yet recorded; empty means only the
        independence check can still refuse the promotion."""
        kinds = {entry.kind for entry in self.evidence}
        return tuple(kind for kind in REQUIRED_FOR_VALIDATED if kind not in kinds)

    @property
    def note(self) -> str:
        """What the record deliberately does not contain."""
        return _NOTE


def register(
    *,
    slug: str,
    hypothesis: str,
    author: str,
    at: datetime,
    reference: str,
    detail: str,
) -> PromotionRecord:
    """Register a hypothesis with its one exploratory run (§3).

    Args:
        slug: The record's file-safe identity.
        hypothesis: The registered hypothesis being tested.
        author: Who is accountable for the candidate; also the floor
            §2.10's independence is measured against.
        at: Registration instant, timezone-aware.
        reference: The exploratory run's id (the run's artefacts stay
            outside version control; this names them).
        detail: What that exploratory run was.

    Returns:
        A new record at ``candidates`` with exactly one evidence
        entry, open with its registration.

    Raises:
        BacktestError: Any identity or evidence refusal above — a
        candidate without a hypothesis or without its exploratory run
        never exists.
    """
    evidence = Evidence(
        kind="exploratory_run",
        reference=reference,
        detail=detail,
        recorded_by=author,
        recorded_at=at,
    )
    transition = Transition(
        at=at,
        actor=author,
        from_stage=_ORIGIN,
        to_stage="candidates",
        reason="hypothesis registered with one exploratory run",
    )
    return PromotionRecord(
        slug=slug,
        hypothesis=hypothesis,
        author=author,
        stage="candidates",
        evidence=(evidence,),
        history=(transition,),
    )


def add_evidence(
    record: PromotionRecord,
    *,
    kind: str,
    reference: str,
    detail: str,
    recorded_by: str,
    at: datetime,
) -> PromotionRecord:
    """Append one evidence entry — never replace one.

    Args:
        record: The current record.
        kind: One of :data:`EVIDENCE_KINDS` not yet recorded.
        reference: How to find the artefact.
        detail: What this entry was.
        recorded_by: Who recorded it.
        at: When, timezone-aware.

    Returns:
        A new record carrying the extra entry; the input is
        untouched (frozen values all the way down).

    Raises:
        BacktestError: A closed-stage record (rejected candidates keep
        exactly the evidence they had, §2.9), a kind already
        recorded, or any refusal from ``Evidence``.
    """
    if record.stage not in ("candidates", "validated"):
        raise BacktestError(
            f"{record.slug} sits at stage {record.stage}, which is closed: a "
            "rejected candidate keeps its evidence so the count of attempts "
            "stays visible (anti-overfitting §2.9), and new evidence belongs "
            "to a new registration"
        )
    if any(entry.kind == kind for entry in record.evidence):
        raise BacktestError(
            f"{record.slug} already records evidence of kind {kind!r}: one "
            "entry per kind, append-only, so nothing can be quietly replaced"
        )
    if kind == "critique" and recorded_by == record.author:
        raise BacktestError(
            f"a critique of {record.slug} must be recorded by someone other "
            f"than its author ({record.author}): §2.10's critique is "
            "independent, and the gate checks it rather than trusts it"
        )
    evidence = Evidence(
        kind=kind,
        reference=reference,
        detail=detail,
        recorded_by=recorded_by,
        recorded_at=at,
    )
    return replace(record, evidence=(*record.evidence, evidence))


def promote_to_validated(
    record: PromotionRecord,
    *,
    actor: str,
    reason: str,
    at: datetime,
) -> PromotionRecord:
    """Promote a candidate to ``validated`` — refused unless §3 is met.

    The product rule, checked here and re-checked on every load:
    held-out test, walk-forward, sensitivity and critique all
    recorded, with the critique recorded by someone other than the
    author (§2.10).

    Args:
        record: The candidate to promote.
        actor: Who promoted it.
        reason: Why — name the evidence it passed on.
        at: When, timezone-aware.

    Returns:
        The record at ``validated`` with the transition appended.

    Raises:
        BacktestError: Not a candidate; any of §3's kinds missing
        (the message names them); a critique recorded by the record's
        own author; an empty reason or actor; a naive timestamp.
    """
    if record.stage != "candidates":
        raise BacktestError(
            f"only a candidate can be promoted to validated; {record.slug} "
            f"already sits at {record.stage}"
        )
    missing = record.missing_for_validated
    if missing:
        raise BacktestError(
            f"{record.slug} cannot be marked validated: evidence missing "
            f"({', '.join(missing)}). The product rule is that validated "
            "requires the held-out test, walk-forward, sensitivity and "
            "critique all recorded (anti-overfitting §3, ROADMAP phase 7) — "
            "there is no partial pass and no flag to weaken it"
        )
    critique = next(entry for entry in record.evidence if entry.kind == "critique")
    if critique.recorded_by == record.author:
        raise BacktestError(
            f"the critique of {record.slug} was recorded by "
            f"{critique.recorded_by}, who authored the candidate: §2.10's "
            "critique must be recorded by someone other than the author, and "
            "this gate checks it rather than trusts it"
        )
    if not reason.strip():
        raise BacktestError(
            f"a promotion records its reason: {record.slug} passed the §3 "
            "gates, and the transition states which evidence it stands on"
        )
    transition = Transition(
        at=at,
        actor=actor,
        from_stage="candidates",
        to_stage="validated",
        reason=reason,
    )
    return replace(record, stage="validated", history=(*record.history, transition))


def reject(
    record: PromotionRecord,
    *,
    actor: str,
    reason: str,
    at: datetime,
) -> PromotionRecord:
    """Reject a candidate, keeping its reason (§2.9).

    Args:
        record: The candidate to reject.
        actor: Who rejected it.
        reason: Why — required; rejected candidates keep their
            reasons so the true number of attempts stays visible.
        at: When, timezone-aware.

    Returns:
        The record at ``rejected`` with the transition appended.

    Raises:
        BacktestError: Not a candidate (a validated strategy that
        must be dropped is archived with its reason, never rewritten
        as never-tried), an empty reason, or a naive timestamp.
    """
    if record.stage != "candidates":
        raise BacktestError(
            f"only a candidate can be rejected; {record.slug} sits at "
            f"{record.stage} — a validated strategy that must be dropped is "
            "archived with its reason, never rewritten as never-tried"
        )
    if not reason.strip():
        raise BacktestError(
            "a rejection keeps its reason (anti-overfitting §2.9: rejected "
            "candidates stay in rejected/ with reasons so the true number of "
            "attempts remains visible)"
        )
    transition = Transition(
        at=at,
        actor=actor,
        from_stage="candidates",
        to_stage="rejected",
        reason=reason,
    )
    return replace(record, stage="rejected", history=(*record.history, transition))


def archive(
    record: PromotionRecord,
    *,
    actor: str,
    reason: str,
    at: datetime,
) -> PromotionRecord:
    """Archive a candidate or a validated strategy, keeping its reason.

    Args:
        record: The record to archive.
        actor: Who archived it.
        reason: Why — required.
        at: When, timezone-aware.

    Returns:
        The record at ``archived`` with the transition appended.

    Raises:
        BacktestError: A closed stage (rejected and archived records
        do not move — §2.9 keeps rejected candidates in rejected/),
        an empty reason, or a naive timestamp.
    """
    if record.stage not in ("candidates", "validated"):
        raise BacktestError(
            f"only a candidate or a validated strategy can be archived; "
            f"{record.slug} sits at {record.stage} — rejected candidates stay "
            "in rejected/ with their reasons (anti-overfitting §2.9)"
        )
    if not reason.strip():
        raise BacktestError(
            "an archive entry keeps its reason: an archived record states why it was closed"
        )
    transition = Transition(
        at=at,
        actor=actor,
        from_stage=record.stage,
        to_stage="archived",
        reason=reason,
    )
    return replace(record, stage="archived", history=(*record.history, transition))


def record_to_json(record: PromotionRecord) -> str:
    """Serialise a record deterministically (sorted keys, trailing newline)."""
    payload: dict[str, object] = {
        "kind": "promotion_record",
        "record_version": RECORD_VERSION,
        "slug": record.slug,
        "hypothesis": record.hypothesis,
        "author": record.author,
        "stage": record.stage,
        "evidence": [
            {
                "kind": entry.kind,
                "reference": entry.reference,
                "detail": entry.detail,
                "recorded_by": entry.recorded_by,
                "recorded_at": entry.recorded_at.isoformat(),
            }
            for entry in record.evidence
        ],
        "history": [
            {
                "at": entry.at.isoformat(),
                "actor": entry.actor,
                "from": entry.from_stage,
                "to": entry.to_stage,
                "reason": entry.reason,
            }
            for entry in record.history
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _mapping(value: object, where: str) -> dict[str, object]:
    """A JSON object from parsed input, or a refusal."""
    if not isinstance(value, dict):
        raise BacktestError(f"{where} is not a JSON object")
    return value


def _sequence(value: object, where: str) -> list[object]:
    """A JSON array from parsed input, or a refusal."""
    if not isinstance(value, list):
        raise BacktestError(f"{where} is not a JSON array")
    return value


def _stamp(value: object, where: str) -> datetime:
    """An ISO-8601 instant from JSON, timezone-aware or refused."""
    text = _text(value, where)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise BacktestError(f"{where} is not an ISO-8601 timestamp: {error}") from error
    return _aware(parsed, where)


def record_from_json(text: str) -> PromotionRecord:
    """Parse and fully validate a record, replaying its history.

    Raises:
        BacktestError: Invalid JSON, a foreign ``kind``, an
        unsupported ``record_version``, a malformed field, or — via
        the record's own constructor — any identity, evidence, gate
        or history refusal. A record whose past could not have
        happened never loads.
    """
    try:
        parsed: object = json.loads(text)
    except ValueError as error:
        raise BacktestError(f"promotion record is not valid JSON: {error}") from error
    root = _mapping(parsed, "promotion record")
    kind = _text(root.get("kind"), "promotion record kind")
    if kind != "promotion_record":
        raise BacktestError(f"not a promotion record (kind={kind!r}); refusing to read it as one")
    version = root.get("record_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise BacktestError(f"record_version must be an integer, got {version!r}")
    if version != RECORD_VERSION:
        raise BacktestError(
            f"record_version {version} is not what this build understands "
            f"({RECORD_VERSION}); refusing to guess its layout"
        )

    evidence_items = _sequence(root.get("evidence"), "evidence")
    evidence: list[Evidence] = []
    for index, item in enumerate(evidence_items):
        where = f"evidence[{index}]"
        entry = _mapping(item, where)
        evidence.append(
            Evidence(
                kind=_text(entry.get("kind"), f"{where}.kind"),
                reference=_text(entry.get("reference"), f"{where}.reference"),
                detail=_text(entry.get("detail"), f"{where}.detail"),
                recorded_by=_text(entry.get("recorded_by"), f"{where}.recorded_by"),
                recorded_at=_stamp(entry.get("recorded_at"), f"{where}.recorded_at"),
            )
        )

    history_items = _sequence(root.get("history"), "history")
    history: list[Transition] = []
    for index, item in enumerate(history_items):
        where = f"history[{index}]"
        entry = _mapping(item, where)
        history.append(
            Transition(
                at=_stamp(entry.get("at"), f"{where}.at"),
                actor=_text(entry.get("actor"), f"{where}.actor"),
                from_stage=_text(entry.get("from"), f"{where}.from"),
                to_stage=_text(entry.get("to"), f"{where}.to"),
                reason=_text(entry.get("reason"), f"{where}.reason"),
            )
        )

    return PromotionRecord(
        slug=_slug_text(root.get("slug"), "slug"),
        hypothesis=_text(root.get("hypothesis"), "hypothesis"),
        author=_text(root.get("author"), "author"),
        stage=_text(root.get("stage"), "stage"),
        evidence=tuple(evidence),
        history=tuple(history),
    )


def iter_records(root: Path | str) -> Iterator[PromotionRecord]:
    """Every record under ``root``, stage by stage then slug sorted.

    A corrupt, misfiled or foreign record raises: a listing that
    skipped what it could not read would hide exactly the record a
    reader needed to see.
    """
    base = Path(root)
    for stage in STAGES:
        directory = base / stage
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as error:
                raise BacktestError(f"cannot read {path}: {error}") from error
            record = record_from_json(text)
            if record.slug != path.stem:
                raise BacktestError(
                    f"{path} holds {record.slug!r}: a record filed under another name is refused"
                )
            if record.stage != stage:
                raise BacktestError(
                    f"{path} holds a record at stage {record.stage}: filed "
                    f"under {stage}/ but claiming another stage"
                )
            yield record


def load_record(root: Path | str, slug: str) -> PromotionRecord:
    """Load one record by slug from whichever stage directory holds it.

    Raises:
        BacktestError: An invalid slug (checked before any path is
        built), no such record, the same slug in two stages, an
        unreadable file, or any refusal from
        :func:`record_from_json`.
    """
    safe_slug = _slug_text(slug, "slug")
    base = Path(root)
    found = [stage for stage in STAGES if (base / stage / f"{safe_slug}.json").is_file()]
    if not found:
        raise BacktestError(
            f"no record named {safe_slug!r} under {base} (looked in {', '.join(STAGES)})"
        )
    if len(found) > 1:
        raise BacktestError(
            f"{safe_slug!r} is recorded in both {' and '.join(found)}: one "
            "strategy has one record, and two copies cannot both be current"
        )
    path = base / found[0] / f"{safe_slug}.json"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise BacktestError(f"cannot read {path}: {error}") from error
    record = record_from_json(text)
    if record.slug != safe_slug:
        raise BacktestError(
            f"{path} holds {record.slug!r}, not {safe_slug!r}: a record filed "
            "under another name is refused"
        )
    return record


def save_record(root: Path | str, record: PromotionRecord) -> Path:
    """Write the record into its stage directory, then retire the old file.

    The new file is written before the previous stage's file is
    removed, so a failed write never loses the record; if the removal
    fails, the refusal says which file to remove by hand so one slug
    keeps one record.

    Returns:
        The path written.
    """
    base = Path(root)
    path = base / record.stage / f"{record.slug}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record_to_json(record), encoding="utf-8")
    except OSError as error:
        raise BacktestError(f"cannot write {path}: {error}") from error
    for stage in STAGES:
        if stage == record.stage:
            continue
        previous = base / stage / f"{record.slug}.json"
        if previous.is_file():
            try:
                previous.unlink()
            except OSError as error:
                raise BacktestError(
                    f"the record was written to {path} but the old file "
                    f"{previous} could not be removed ({error}): remove it by "
                    "hand so one slug keeps one record"
                ) from error
    return path
