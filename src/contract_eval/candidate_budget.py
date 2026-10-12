"""Cumulative EUR spend ledger for paid candidate attempts.

The portfolio cap is EUR 100 across every attempt, retry and plan version. This ledger
is the only record allowed to say how much of it is left. A reservation holds the worst
case for one arm of one experiment before dispatch, a settlement replaces it by an upper
estimate from provider-reported usage, a void releases a reservation whose attempts never
ran. Prices are never typed from memory: a price row carries the date it was read from
the provider's price page and that page's address, and a stale row refuses to reserve.
Money is integer minor units (cents), as elsewhere in the portfolio.

What the ledger is and is not:

- Entries are appended in time order and validated as a history. A closure must follow
  its reservation, and no reservation may take committed spend past the cap.
- Every amount is an upper estimate, not an invoice. A price converted from another
  currency carries a fixed allowance for rate movement, stored with the reservation.
- A settlement states a fact. It may exceed its reservation and even the cap, and is then
  reported as an overrun instead of being refused: a ledger that cannot record what
  happened is worse than one that shows a breach.
- The file is maintained by its operator. Its checks make mistakes and after-the-fact
  edits visible to `candidate_experiment aggregate`; they are not a signature.

Reserving, settling and voiding go through `candidate_experiment`, which knows the arm's
preregistration and its attempts. This module's command line only shows the status and
records a verified price.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contract_eval.candidates import parse_instant

LEDGER_SCHEMA = "mycounsel.spend-ledger.v1"
ENTRY_ID = r"^[a-z0-9][a-z0-9-]{2,63}$"
HEX64 = r"^[a-f0-9]{64}$"
TOKENS_PER_PRICE_UNIT = 1_000_000
# Added to every amount derived from a price that was converted into EUR, so a rate that
# moves between verification and billing cannot push spend past the cap. A reservation
# stores the value it was made with; changing this constant never rewrites history.
CONVERSION_ALLOWANCE_PERCENT = 10


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def format_instant(instant: datetime) -> str:
    """UTC, whole seconds, with a Z: the one spelling of a moment in this ledger."""
    if instant.tzinfo is None:
        raise ValueError("an instant needs a time zone")
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class Price(Strict):
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    region: str = Field(min_length=1)
    currency: Literal["EUR"]
    # Currency of the provider's own list price. Anything but EUR means the figures below
    # were converted, which needs a note and triggers the allowance.
    listCurrency: str = Field(pattern=r"^[A-Z]{3}$")
    inputMinorUnitsPerMillionTokens: int = Field(gt=0)
    # Applies to every billed output token, thinking included.
    outputMinorUnitsPerMillionTokens: int = Field(gt=0)
    verifiedOn: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sourceUrl: str = Field(pattern=r"^https://")
    # For a converted price: the list figures, the rate, the rate's date and source.
    conversionNote: str = ""

    @model_validator(mode="after")
    def conversion_is_explained(self) -> "Price":
        date.fromisoformat(self.verifiedOn)
        if self.listCurrency != "EUR" and not self.conversionNote.strip():
            raise ValueError("a price converted into EUR states its list figures, rate and rate date")
        return self

    def key(self) -> tuple[str, str, str]:
        return self.model, self.provider, self.region

    def allowance_percent(self) -> int:
        return 0 if self.listCurrency == "EUR" else CONVERSION_ALLOWANCE_PERCENT


class Entry(Strict):
    id: str = Field(pattern=ENTRY_ID)
    kind: Literal["RESERVATION", "SETTLEMENT", "VOID"]
    experimentId: str = Field(min_length=1)
    arm: str = Field(min_length=1)
    attempts: int = Field(ge=1)
    amountMinorUnits: int = Field(ge=0)
    # UTC instant the entry was written. Order checks against attempt start times use it.
    recordedAt: str
    # RESERVATION only: everything needed to recompute the hold and to settle it later
    # at the price it was reserved at, and the hash of what the arm was preregistered as.
    maxInputTokensPerAttempt: int | None = Field(default=None, ge=1)
    maxOutputTokensPerAttempt: int | None = Field(default=None, ge=1)
    retryMultiplier: int | None = Field(default=None, ge=1)
    perAttemptMinorUnits: int | None = Field(default=None, ge=1)
    conversionAllowancePercent: int | None = Field(default=None, ge=0, le=100)
    price: Price | None = None
    preregistrationSha256: str | None = Field(default=None, pattern=HEX64)
    # SETTLEMENT and VOID: the reservation this entry closes.
    reservationId: str | None = None
    # SETTLEMENT only: what the amount was computed from.
    observedAttempts: int | None = Field(default=None, ge=0)
    attemptsWithoutUsage: int | None = Field(default=None, ge=0)
    evidenceSha256: str | None = Field(default=None, pattern=HEX64)
    note: str = ""

    @model_validator(mode="after")
    def shape_by_kind(self) -> "Entry":
        if format_instant(parse_instant(self.recordedAt)) != self.recordedAt:
            raise ValueError("recordedAt is a UTC instant written as YYYY-MM-DDTHH:MM:SSZ")
        hold = {"maxInputTokensPerAttempt": self.maxInputTokensPerAttempt,
                "maxOutputTokensPerAttempt": self.maxOutputTokensPerAttempt,
                "retryMultiplier": self.retryMultiplier, "perAttemptMinorUnits": self.perAttemptMinorUnits,
                "conversionAllowancePercent": self.conversionAllowancePercent, "price": self.price,
                "preregistrationSha256": self.preregistrationSha256}
        evidence = {"observedAttempts": self.observedAttempts, "attemptsWithoutUsage": self.attemptsWithoutUsage,
                    "evidenceSha256": self.evidenceSha256}
        if self.kind == "RESERVATION":
            if self.reservationId is not None or any(value is not None for value in evidence.values()):
                raise ValueError("a reservation does not close another entry")
            absent = [name for name, value in hold.items() if value is None]
            if absent:
                raise ValueError("a reservation records " + ", ".join(absent))
            if self.price.listCurrency == "EUR" and self.conversionAllowancePercent != 0:
                raise ValueError("a price listed in EUR carries no conversion allowance")
            expected = attempt_hold_minor_units(self.price, self.maxInputTokensPerAttempt,
                                                self.maxOutputTokensPerAttempt, self.conversionAllowancePercent)
            if self.perAttemptMinorUnits != expected:
                raise ValueError("per-attempt amount does not follow from the recorded price and token maxima")
            if self.amountMinorUnits != expected * self.attempts * self.retryMultiplier:
                raise ValueError("reservation amount does not follow from attempts, retries and the per-attempt amount")
            return self
        if any(value is not None for value in hold.values()):
            raise ValueError("only a reservation records token maxima, a price and a preregistration")
        if self.reservationId is None:
            raise ValueError(f"a {self.kind.lower()} names the reservation it closes")
        if self.kind == "VOID":
            if any(value is not None for value in evidence.values()):
                raise ValueError("a void has no attempts to settle")
            if self.amountMinorUnits != 0:
                raise ValueError("a void releases the whole reservation")
            return self
        absent = [name for name, value in evidence.items() if value is None]
        if absent:
            raise ValueError("a settlement records " + ", ".join(absent))
        if self.attemptsWithoutUsage > self.observedAttempts:
            raise ValueError("attempts without usage are a share of the observed attempts")
        return self


class Ledger(Strict):
    schema_: Literal["mycounsel.spend-ledger.v1"] = Field(alias="schema")
    currency: Literal["EUR"]
    capMinorUnits: int = Field(gt=0)
    maxPriceAgeDays: int = Field(default=30, ge=1, le=90)
    prices: list[Price] = Field(default_factory=list)
    entries: list[Entry] = Field(default_factory=list)

    @model_validator(mode="after")
    def history_is_sound(self) -> "Ledger":
        ids = [entry.id for entry in self.entries]
        if len(set(ids)) != len(ids):
            raise ValueError("ledger entry ids must be unique")
        reservations: dict[str, Entry] = {}
        closed: set[str] = set()
        committed = 0
        previous: datetime | None = None
        for entry in self.entries:
            instant = parse_instant(entry.recordedAt)
            if previous is not None and instant < previous:
                raise ValueError(f"entry {entry.id} is dated before the entry above it; the ledger is appended in time order")
            previous = instant
            if entry.kind == "RESERVATION":
                if any((r.experimentId, r.arm) == (entry.experimentId, entry.arm) and r.id not in closed
                       for r in reservations.values()):
                    raise ValueError(f"arm {entry.arm} of {entry.experimentId} holds two open reservations")
                reservations[entry.id] = entry
                committed += entry.amountMinorUnits
                # A reservation is a choice and must fit. A settlement is a fact and is
                # recorded even when it does not; status() then reports the breach.
                if committed > self.capMinorUnits:
                    raise ValueError(f"reservation {entry.id} takes committed spend past the cap")
                continue
            target = reservations.get(entry.reservationId or "")
            if target is None or (target.experimentId, target.arm) != (entry.experimentId, entry.arm):
                raise ValueError(f"{entry.kind.lower()} {entry.id} does not close an earlier reservation of the same arm")
            if target.id in closed:
                raise ValueError(f"reservation {target.id} is closed twice")
            if entry.kind == "SETTLEMENT" and entry.observedAttempts > target.attempts:
                raise ValueError(f"settlement {entry.id} observes more attempts than its reservation covers")
            closed.add(target.id)
            committed += entry.amountMinorUnits - target.amountMinorUnits
        keys = [price.key() for price in self.prices]
        if len(set(keys)) != len(keys):
            raise ValueError("one price row per model, provider and region")
        return self


def load_ledger(path: Path) -> Ledger:
    return Ledger.model_validate_json(path.read_text(encoding="utf-8"))


def save_ledger(ledger: Ledger, path: Path) -> None:
    checked = Ledger.model_validate(ledger.model_dump(by_alias=True))
    path.write_text(json.dumps(checked.model_dump(by_alias=True, exclude_none=True), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _append(ledger: Ledger, entry: Entry) -> None:
    """Add an entry only if the whole ledger still validates; never leave it half-applied."""
    candidate = ledger.model_dump(by_alias=True)
    candidate["entries"].append(entry.model_dump())
    Ledger.model_validate(candidate)
    ledger.entries.append(entry)


def find_entry(ledger: Ledger, entry_id: str) -> Entry | None:
    return next((e for e in ledger.entries if e.id == entry_id), None)


def closure_of(ledger: Ledger, reservation_id: str) -> Entry | None:
    return next((e for e in ledger.entries if e.kind != "RESERVATION" and e.reservationId == reservation_id), None)


def open_reservations(ledger: Ledger) -> list[Entry]:
    return [e for e in ledger.entries if e.kind == "RESERVATION" and closure_of(ledger, e.id) is None]


def committed_minor_units(ledger: Ledger) -> int:
    settled = sum(e.amountMinorUnits for e in ledger.entries if e.kind == "SETTLEMENT")
    return settled + sum(e.amountMinorUnits for e in open_reservations(ledger))


def remaining_minor_units(ledger: Ledger) -> int:
    return ledger.capMinorUnits - committed_minor_units(ledger)


def price_is_fresh(price: Price, on: date, max_age_days: int) -> bool:
    age = (on - date.fromisoformat(price.verifiedOn)).days
    return 0 <= age <= max_age_days


def find_price(ledger: Ledger, *, model: str, provider: str, region: str, today: date) -> Price:
    for price in ledger.prices:
        if price.key() == (model, provider, region):
            age = (today - date.fromisoformat(price.verifiedOn)).days
            if age < 0:
                raise ValueError(f"price for {model} is dated in the future")
            if age > ledger.maxPriceAgeDays:
                raise ValueError(f"price for {model} was verified {age} days ago; re-read the provider's page first")
            return price
    raise ValueError(f"no verified price for {model} via {provider} in {region}; add one from the provider's page")


def _minor_units(token_price_units: int, allowance_percent: int) -> int:
    """Round a sum of tokens x price up to whole minor units, with the conversion allowance.

    `token_price_units` is sum(tokens x minor units per million tokens). Integer
    arithmetic throughout: a float here could round a hold down by a cent.
    """
    return -(-(token_price_units * (100 + allowance_percent)) // (TOKENS_PER_PRICE_UNIT * 100))


def _token_price_units(price: Price, input_tokens: int, output_tokens: int) -> int:
    return (input_tokens * price.inputMinorUnitsPerMillionTokens
            + output_tokens * price.outputMinorUnitsPerMillionTokens)


def attempt_hold_minor_units(price: Price, max_input_tokens: int, max_output_tokens: int,
                             allowance_percent: int) -> int:
    """Worst-case cost of ONE attempt in EUR minor units, before the retry multiplier.

    `max_output_tokens` is the provider-side output ceiling the gateway sends, thinking
    included: the answer allowance plus the gateway's thinking headroom. Both gateways
    bill thinking as output, so nothing is added here; a caller that passed only the
    answer allowance would under-reserve. The result is rounded up to a whole cent per
    attempt, with the conversion allowance on top where the price was converted.
    """
    return _minor_units(_token_price_units(price, max_input_tokens, max_output_tokens), allowance_percent)


def settlement_minor_units(reservation: Entry, usages: list[tuple[int, int] | None]) -> dict:
    """Upper estimate of what the observed attempts cost, at the reserved price.

    Each item is (input tokens, billed output tokens) as the provider reported them, or
    None for an attempt that ran without reporting usage. Reported usage is summed and
    rounded up once. An attempt without usage, or with a reported input of zero, is
    charged its full per-attempt hold, because a failed call can still have been billed
    and no real call has an empty input. Attempts that never ran are not in the list and
    cost nothing. Usage above the reserved maxima is charged as reported and counted,
    since it means the hold was set too low.

    The recording shows one response per attempt. A request the provider's client
    repeated internally may have been billed more than once; the reservation's retry
    multiplier is the allowance for that, and the provider's invoice settles it.
    """
    if reservation.kind != "RESERVATION":
        raise ValueError("only a reservation can be settled")
    price = reservation.price
    reported = [usage for usage in usages if usage is not None and usage[0] > 0]
    silent = len(usages) - len(reported)
    above = sum(1 for i, o in reported
                if i > reservation.maxInputTokensPerAttempt or o > reservation.maxOutputTokensPerAttempt)
    amount = (_minor_units(sum(_token_price_units(price, i, o) for i, o in reported),
                           reservation.conversionAllowancePercent)
              + silent * reservation.perAttemptMinorUnits)
    return {"amountMinorUnits": amount, "attemptsWithoutUsage": silent, "attemptsAboveReservedMaxima": above}


def set_price(ledger: Ledger, price: Price) -> None:
    """Add or refresh the one row for a model, provider and region.

    While a reservation made at other figures is still open for that row, the refresh is
    refused: the arm would be dispatched and settled at a price that is no longer the
    provider's. Void that reservation and reserve again.
    """
    for reservation in open_reservations(ledger):
        held = reservation.price
        if held.key() == price.key() and (
                held.inputMinorUnitsPerMillionTokens, held.outputMinorUnitsPerMillionTokens,
                held.listCurrency) != (
                price.inputMinorUnitsPerMillionTokens, price.outputMinorUnitsPerMillionTokens,
                price.listCurrency):
            raise ValueError(
                f"reservation {reservation.id} is open at the old price for {price.model}; "
                "void it and reserve again before changing the price")
    ledger.prices[:] = [p for p in ledger.prices if p.key() != price.key()] + [price]


def reserve(ledger: Ledger, *, entry_id: str, experiment_id: str, arm: str, attempts: int, model: str,
            provider: str, region: str, max_input_tokens: int, max_output_tokens: int,
            retry_multiplier: int, preregistration_sha256: str, now: datetime, note: str = "") -> Entry:
    """Hold the worst case for an arm. Refuses rather than overdraws; never resets the cap."""
    if any((e.experimentId, e.arm) == (experiment_id, arm) for e in open_reservations(ledger)):
        raise ValueError(f"arm {arm} of {experiment_id} already holds an open reservation")
    price = find_price(ledger, model=model, provider=provider, region=region,
                       today=now.astimezone(timezone.utc).date())
    allowance = price.allowance_percent()
    per_attempt = attempt_hold_minor_units(price, max_input_tokens, max_output_tokens, allowance)
    amount = per_attempt * attempts * retry_multiplier
    remaining = remaining_minor_units(ledger)
    if amount > remaining:
        raise ValueError(
            f"reservation of {amount} minor units exceeds the remaining {remaining}; "
            "reduce the design or stop before dispatch and record the evidence gap")
    entry = Entry(id=entry_id, kind="RESERVATION", experimentId=experiment_id, arm=arm, attempts=attempts,
                  maxInputTokensPerAttempt=max_input_tokens, maxOutputTokensPerAttempt=max_output_tokens,
                  retryMultiplier=retry_multiplier, perAttemptMinorUnits=per_attempt,
                  conversionAllowancePercent=allowance, price=price,
                  preregistrationSha256=preregistration_sha256, amountMinorUnits=amount,
                  recordedAt=format_instant(now), note=note)
    _append(ledger, entry)
    return entry


def _open(ledger: Ledger, reservation_id: str) -> Entry:
    reservation = next((e for e in open_reservations(ledger) if e.id == reservation_id), None)
    if reservation is None:
        raise ValueError(f"no open reservation {reservation_id}")
    return reservation


def settle(ledger: Ledger, *, entry_id: str, reservation_id: str, amount_minor_units: int,
           observed_attempts: int, attempts_without_usage: int, evidence_sha256: str, now: datetime,
           note: str = "") -> Entry:
    """Replace a reservation by the upper estimate of what its attempts cost."""
    reservation = _open(ledger, reservation_id)
    entry = Entry(id=entry_id, kind="SETTLEMENT", experimentId=reservation.experimentId, arm=reservation.arm,
                  attempts=reservation.attempts, amountMinorUnits=amount_minor_units,
                  recordedAt=format_instant(now), reservationId=reservation_id,
                  observedAttempts=observed_attempts, attemptsWithoutUsage=attempts_without_usage,
                  evidenceSha256=evidence_sha256, note=note)
    _append(ledger, entry)
    return entry


def void(ledger: Ledger, *, entry_id: str, reservation_id: str, now: datetime, note: str = "") -> Entry:
    """Release a reservation whose attempts never ran. The caller proves that they did not."""
    reservation = _open(ledger, reservation_id)
    entry = Entry(id=entry_id, kind="VOID", experimentId=reservation.experimentId, arm=reservation.arm,
                  attempts=reservation.attempts, amountMinorUnits=0, recordedAt=format_instant(now),
                  reservationId=reservation_id, note=note)
    _append(ledger, entry)
    return entry


def status(ledger: Ledger) -> dict:
    reservations = {e.id: e for e in ledger.entries if e.kind == "RESERVATION"}
    settlements = [e for e in ledger.entries if e.kind == "SETTLEMENT"]
    overruns = {e.id: e.amountMinorUnits - reservations[e.reservationId].amountMinorUnits
                for e in settlements if e.amountMinorUnits > reservations[e.reservationId].amountMinorUnits}
    remaining = remaining_minor_units(ledger)
    return {
        "currency": ledger.currency, "capMinorUnits": ledger.capMinorUnits,
        "settledMinorUnits": sum(e.amountMinorUnits for e in settlements),
        "openReservationMinorUnits": sum(e.amountMinorUnits for e in open_reservations(ledger)),
        "remainingMinorUnits": remaining,
        "capExceeded": remaining < 0,
        "settlementsAboveTheirReservation": overruns,
        "openReservations": [e.id for e in open_reservations(ledger)],
        "voidedReservations": [e.reservationId for e in ledger.entries if e.kind == "VOID"],
        "verifiedPrices": [f"{p.model} via {p.provider}/{p.region} on {p.verifiedOn}" for p in ledger.prices],
        "conversionAllowancePercent": CONVERSION_ALLOWANCE_PERCENT,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", type=Path, default=Path("candidates/mycounsel/spend-ledger.json"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show cap, settled, reserved and remaining amounts")
    price = sub.add_parser("price", help="add or refresh a price row read from the provider's page")
    for flag in ("--model", "--provider", "--region", "--verified-on", "--source-url", "--list-currency"):
        price.add_argument(flag, required=True)
    price.add_argument("--input-minor-units-per-million", type=int, required=True)
    price.add_argument("--output-minor-units-per-million", type=int, required=True)
    price.add_argument("--conversion-note", default="")
    args = parser.parse_args(argv)

    ledger = load_ledger(args.ledger)
    if args.cmd == "status":
        print(json.dumps(status(ledger), indent=2))
        return
    set_price(ledger, Price(
        model=args.model, provider=args.provider, region=args.region, currency="EUR",
        listCurrency=args.list_currency,
        inputMinorUnitsPerMillionTokens=args.input_minor_units_per_million,
        outputMinorUnitsPerMillionTokens=args.output_minor_units_per_million,
        verifiedOn=args.verified_on, sourceUrl=args.source_url, conversionNote=args.conversion_note))
    save_ledger(ledger, args.ledger)
    print(f"Price row for {args.model} via {args.provider}/{args.region} recorded as verified on {args.verified_on}.")


if __name__ == "__main__":
    main()
