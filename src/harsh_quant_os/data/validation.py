"""Validation for a batch of bars.

The rules are data-platform.md section 3, and Phase 3's exit criteria:
invalid data is quarantined, never silently repaired or invented; gaps are
reported as gaps.

What this module deliberately does **not** do:

- **It never edits a bar.** Detection changes the *report*; the bars that
  come out are the bars that went in, minus exact duplicates. Winsorising
  or clamping an outlier would be inventing a price the provider did not
  send.
- **It does not reorder anything.** Timestamp order is checked, and a batch
  that fails is rejected with a reason. Sorting it would repair the batch
  behind the caller's back, which is what "silently repaired" means.
- **It does not fill gaps.** A gap becomes an interval in the report, with
  the count of bars that should have been there and were not.

Two checks from section 3 are **not implemented** and are not approximated
either: comparison against the instrument's session calendar, and the
optional second-source cross-check. Neither an exchange calendar nor a
second provider exists yet. Until one does, weekday gaps in daily bars
appear as gaps - which is a true statement about what arrived, and the
report says so in ``notes`` rather than pretending the calendar was known.

Duplicate policy: the **first** bar at a timestamp wins and later ones are
dropped and counted. Which one wins is fixed rather than incidental, so the
same input always produces the same output - Phase 3 requires a re-ingest
to produce an identical version. A dropped duplicate that disagreed with
the bar kept is a stronger signal than a repeat, and is reported as such.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harsh_quant_os.contracts.provenance import DataQualityStatus, Timeframe
from harsh_quant_os.data.errors import InvalidProviderPayload
from harsh_quant_os.data.providers import Bar

__all__ = [
    "Gap",
    "ValidationReport",
    "parse_rows",
    "validate_bars",
]

#: Bar spacing used for gap detection. ``None`` means the timeframe has no
#: fixed interval, so gap detection is impossible for it rather than wrong:
#: ticks arrive when they arrive, and month lengths are not constant.
_CADENCE: dict[Timeframe, timedelta | None] = {
    Timeframe.TICK: None,
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.M30: timedelta(minutes=30),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
    Timeframe.W1: timedelta(weeks=1),
    Timeframe.MN1: None,
}

#: Conventional threshold for the modified z-score used below. Not a claim
#: about any market - a configurable convention, stated as one.
DEFAULT_OUTLIER_SIGMA = Decimal("3.5")

#: Below this many bars the outlier rule has too little to measure with.
DEFAULT_MINIMUM_FOR_OUTLIERS = 20


class Gap(BaseModel):
    """An interval where bars were expected and did not arrive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    after: datetime = Field(description="Last bar seen before the gap.")
    before: datetime = Field(description="First bar seen after the gap.")
    expected_missing: int = Field(ge=1, description="Bars that should have been there.")


class ValidationReport(BaseModel):
    """What validation found. Immutable, and it never carries a repaired bar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: DataQualityStatus
    reasons: tuple[str, ...] = Field(description="Why the status is what it is.")
    notes: tuple[str, ...] = Field(description="What was not checked, and why.")
    received: int = Field(ge=0)
    duplicates_removed: int = Field(ge=0)
    disagreeing_duplicates: int = Field(
        ge=0, description="Duplicates whose values differed from the bar kept."
    )
    gaps: tuple[Gap, ...]
    outliers: tuple[datetime, ...]
    accepted_bars: tuple[Bar, ...]

    @property
    def is_storable(self) -> bool:
        """Only valid data may be stored as valid; suspect data may be stored
        but flagged, and invalid data may not be stored at all."""
        return self.status is not DataQualityStatus.INVALID


def parse_rows(
    rows: Sequence[dict[str, object]],
    *,
    symbol: str,
    timeframe: Timeframe,
) -> list[Bar]:
    """Convert raw provider rows into bars, or refuse the whole batch.

    Schema failure quarantines the *batch*, per section 3: one malformed
    row means the payload is not what the provider claimed, and accepting
    the rows around it would silently drop data nobody chose to drop.

    The raised message names the row and the offending field. It does not
    echo the row's values - a payload can contain anything, and this
    message ends up in a log.
    """
    bars: list[Bar] = []
    for index, row in enumerate(rows):
        payload = dict(row)
        payload["symbol"] = symbol
        payload["timeframe"] = timeframe
        try:
            bars.append(Bar.model_validate(payload))
        except ValidationError as exc:
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first.get("loc", ()))
            raise InvalidProviderPayload(
                f"row {index} failed schema validation at field '{location}': {first.get('msg')}"
            ) from None
    return bars


def validate_bars(
    bars: Sequence[Bar],
    *,
    timeframe: Timeframe,
    outlier_sigma: Decimal = DEFAULT_OUTLIER_SIGMA,
    minimum_for_outliers: int = DEFAULT_MINIMUM_FOR_OUTLIERS,
) -> ValidationReport:
    """Check a batch and report. Never modifies, never sorts, never fills."""
    received = len(bars)
    notes: list[str] = []

    if received == 0:
        return ValidationReport(
            status=DataQualityStatus.INVALID,
            reasons=("the batch contained no bars; there is nothing to store",),
            notes=(),
            received=0,
            duplicates_removed=0,
            disagreeing_duplicates=0,
            gaps=(),
            outliers=(),
            accepted_bars=(),
        )

    # The caller states which timeframe it is validating against; the bars
    # state theirs. If they disagree the gap arithmetic below would be done
    # against the wrong spacing, so the batch is refused rather than
    # measured with a ruler that does not match it.
    mismatched = sorted({bar.timeframe.value for bar in bars if bar.timeframe is not timeframe})
    if mismatched:
        return ValidationReport(
            status=DataQualityStatus.INVALID,
            reasons=(
                f"bars carry timeframe(s) {', '.join(mismatched)} but validation was asked "
                f"for {timeframe.value}",
            ),
            notes=tuple(notes),
            received=received,
            duplicates_removed=0,
            disagreeing_duplicates=0,
            gaps=(),
            outliers=(),
            accepted_bars=(),
        )

    # --- duplicates ---------------------------------------------------
    # First bar at a timestamp wins; later ones are dropped and counted.
    kept: list[Bar] = []
    duplicates = 0
    disagreeing = 0
    for bar in bars:
        if kept and bar.timestamp == kept[-1].timestamp:
            duplicates += 1
            previous = kept[-1]
            if (
                bar.open != previous.open
                or bar.high != previous.high
                or bar.low != previous.low
                or bar.close != previous.close
                or bar.volume != previous.volume
            ):
                disagreeing += 1
            continue
        kept.append(bar)

    # Duplicate detection above only sees a repeat next to its twin, so the
    # whole list is checked. A repeat anywhere forces the sequence down and
    # back up, which means some adjacent pair is not increasing - so a
    # single pass over neighbours is enough, and no set is needed.
    strictly_increasing = all(
        later.timestamp > earlier.timestamp for earlier, later in pairwise(kept)
    )

    # --- timestamp order ----------------------------------------------
    # Rejected, not sorted: see the module docstring.
    if not strictly_increasing:
        return ValidationReport(
            status=DataQualityStatus.INVALID,
            reasons=("timestamps are not strictly increasing; the batch is rejected",),
            notes=tuple(notes),
            received=received,
            duplicates_removed=duplicates,
            disagreeing_duplicates=disagreeing,
            gaps=(),
            outliers=(),
            accepted_bars=(),
        )

    reasons: list[str] = []
    if duplicates:
        reasons.append(f"{duplicates} duplicate timestamp(s) dropped, keeping the first occurrence")
    if disagreeing:
        reasons.append(
            f"{disagreeing} duplicate(s) disagreed with the bar kept, so the provider "
            "reported two different values for one instant"
        )

    # --- gaps ----------------------------------------------------------
    # Recorded, never filled. Without a session calendar, non-trading
    # intervals count as gaps too - see notes.
    gaps: list[Gap] = []
    cadence = _CADENCE[timeframe]
    if cadence is None:
        notes.append(f"gaps were not computed: {timeframe.value} has no fixed interval")
    else:
        for earlier, later in pairwise(kept):
            steps = (later.timestamp - earlier.timestamp) // cadence
            if steps > 1:
                gaps.append(
                    Gap(
                        after=earlier.timestamp,
                        before=later.timestamp,
                        expected_missing=steps - 1,
                    )
                )
        if gaps and timeframe is Timeframe.D1:
            notes.append(
                "gaps are computed against raw 1-day spacing; without a session "
                "calendar, weekends and holidays appear as gaps"
            )

    # --- outliers --------------------------------------------------------
    # Detection only. Nothing found here is altered - it is flagged.
    outliers: list[datetime] = []
    if len(kept) < minimum_for_outliers:
        notes.append(
            f"outliers were not judged: {len(kept)} bar(s) is below the "
            f"{minimum_for_outliers} needed"
        )
    else:
        values = [bar.high - bar.low for bar in kept]
        median = statistics.median(values)
        median_absolute_deviation = statistics.median([abs(value - median) for value in values])
        if median_absolute_deviation == 0:
            notes.append(
                "outliers were not judged: every bar has the same range, so the "
                "rule has no variation to measure with"
            )
        else:
            for bar, value in zip(kept, values, strict=True):
                score = (Decimal("0.6745") * (value - median)) / median_absolute_deviation
                if abs(score) > outlier_sigma:
                    outliers.append(bar.timestamp)

    # --- status -----------------------------------------------------------
    # Two independent reasons to distrust the batch: a price beyond the
    # distribution, and a provider that gave two answers for one instant.
    # Either is enough for `suspect`. Neither is enough for `invalid`,
    # because both are reported rather than corrected.
    if outliers:
        reasons.append(
            f"{len(outliers)} bar(s) flagged as outliers; values are reported as found, "
            "not adjusted"
        )

    if outliers or disagreeing:
        status = DataQualityStatus.SUSPECT
    else:
        status = DataQualityStatus.VALID
        if not reasons:
            reasons.append("schema, ordering, duplicates, gaps and outliers all checked")

    return ValidationReport(
        status=status,
        reasons=tuple(reasons),
        notes=tuple(notes),
        received=received,
        duplicates_removed=duplicates,
        disagreeing_duplicates=disagreeing,
        gaps=tuple(gaps),
        outliers=tuple(outliers),
        accepted_bars=tuple(kept),
    )
