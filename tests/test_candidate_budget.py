"""The EUR cap is cumulative: holds are whole cents, settlements are facts, the history is checked.

Every amount below is worked out by hand from the test price of 300 minor units per million
input tokens and 1500 per million output tokens:

- one attempt at 6000 input and 12096 output tokens: 1,800,000 + 18,144,000 = 19,944,000
  price units = 19.944 minor units, held as 20; with the 10 per cent allowance 21.9384, held as 22
- one arm of twelve attempts with retry multiplier 2: 20 x 12 x 2 = 480 (converted price: 528)
- one reported attempt of 2000 input and 3000 output tokens: 600,000 + 4,500,000 = 5.1 minor units

Experiment names, notes, hashes and the conversion note are test text and validate nothing.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from contract_eval import candidate_budget
from contract_eval.candidate_budget import (
    Entry, Ledger, Price, attempt_hold_minor_units, closure_of, committed_minor_units, find_entry,
    find_price, format_instant, load_ledger, main, now_utc, open_reservations, price_is_fresh,
    remaining_minor_units, reserve, save_ledger, set_price, settle, settlement_minor_units, status, void,
)

SEED = Path(__file__).resolve().parents[1] / "candidates" / "mycounsel" / "spend-ledger.json"
NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 12, 10, 0, 0, tzinfo=timezone.utc)
LATEST = datetime(2026, 10, 12, 11, 0, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 12)
SELECTOR = {"model": "test-model", "provider": "test-provider", "region": "eu"}
PREREGISTRATION = "a" * 64
EVIDENCE = "b" * 64
TEST_NOTE = "Test conversion note, not a real rate: list price in USD at EUR 1 = USD 1.10."


def price_row(**overrides) -> dict:
    row = {**SELECTOR, "currency": "EUR", "listCurrency": "EUR",
           "inputMinorUnitsPerMillionTokens": 300, "outputMinorUnitsPerMillionTokens": 1500,
           "verifiedOn": "2026-10-01", "sourceUrl": "https://example.invalid/test-prices",
           "conversionNote": ""}
    row.update(overrides)
    return row


def converted_row(**overrides) -> dict:
    return price_row(**{"listCurrency": "USD", "conversionNote": TEST_NOTE, **overrides})


def ledger_file(**overrides) -> dict:
    base = {"schema": "mycounsel.spend-ledger.v1", "currency": "EUR", "capMinorUnits": 10000,
            "prices": [price_row()], "entries": []}
    base.update(overrides)
    return base


def book(**overrides) -> Ledger:
    return Ledger.model_validate(ledger_file(**overrides))


def hold(ledger: Ledger, entry_id="res-1", arm="baseline", **overrides) -> Entry:
    args = {"experiment_id": "test-exp", "attempts": 12, "max_input_tokens": 6000, "max_output_tokens": 12096,
            "retry_multiplier": 2, "preregistration_sha256": PREREGISTRATION, "now": NOW, **SELECTOR}
    args.update(overrides)
    return reserve(ledger, entry_id=entry_id, arm=arm, **args)


def close(ledger: Ledger, entry_id="set-1", reservation_id="res-1", **overrides) -> Entry:
    args = {"amount_minor_units": 123, "observed_attempts": 12, "attempts_without_usage": 0,
            "evidence_sha256": EVIDENCE, "now": LATER}
    args.update(overrides)
    return settle(ledger, entry_id=entry_id, reservation_id=reservation_id, **args)


def reservation_row(**overrides) -> dict:
    """A reservation as it stands in a ledger file, every figure written out by hand."""
    row = {"id": "res-1", "kind": "RESERVATION", "experimentId": "test-exp", "arm": "baseline",
           "attempts": 12, "amountMinorUnits": 480, "recordedAt": "2026-10-12T09:00:00Z",
           "maxInputTokensPerAttempt": 6000, "maxOutputTokensPerAttempt": 12096, "retryMultiplier": 2,
           "perAttemptMinorUnits": 20, "conversionAllowancePercent": 0, "price": price_row(),
           "preregistrationSha256": PREREGISTRATION, "note": "test reservation"}
    row.update(overrides)
    return row


def converted_reservation_row(**overrides) -> dict:
    return reservation_row(**{"amountMinorUnits": 528, "perAttemptMinorUnits": 22,
                              "conversionAllowancePercent": 10, "price": converted_row(), **overrides})


def settlement_row(**overrides) -> dict:
    row = {"id": "set-1", "kind": "SETTLEMENT", "experimentId": "test-exp", "arm": "baseline",
           "attempts": 12, "amountMinorUnits": 123, "recordedAt": "2026-10-12T10:00:00Z",
           "reservationId": "res-1", "observedAttempts": 12, "attemptsWithoutUsage": 0,
           "evidenceSha256": EVIDENCE, "note": "test settlement"}
    row.update(overrides)
    return row


def void_row(**overrides) -> dict:
    row = {"id": "void-1", "kind": "VOID", "experimentId": "test-exp", "arm": "baseline",
           "attempts": 12, "amountMinorUnits": 0, "recordedAt": "2026-10-12T10:00:00Z",
           "reservationId": "res-1", "note": "test void, nothing was dispatched"}
    row.update(overrides)
    return row


def without(row: dict, field: str) -> dict:
    return {key: value for key, value in row.items() if key != field}


def estimate(amount: int, silent: int = 0, above: int = 0) -> dict:
    return {"amountMinorUnits": amount, "attemptsWithoutUsage": silent, "attemptsAboveReservedMaxima": above}


HOLD_FIELDS = {"maxInputTokensPerAttempt": 6000, "maxOutputTokensPerAttempt": 12096, "retryMultiplier": 2,
               "perAttemptMinorUnits": 20, "conversionAllowancePercent": 0, "price": price_row(),
               "preregistrationSha256": PREREGISTRATION}
EVIDENCE_FIELDS = {"observedAttempts": 0, "attemptsWithoutUsage": 0, "evidenceSha256": EVIDENCE}


# --- price rows ---------------------------------------------------------------------------


def test_a_price_listed_in_eur_carries_no_allowance():
    row = Price.model_validate(price_row())
    assert row.allowance_percent() == 0
    assert row.key() == ("test-model", "test-provider", "eu")


def test_a_converted_price_carries_the_ten_per_cent_allowance():
    assert candidate_budget.CONVERSION_ALLOWANCE_PERCENT == 10
    assert Price.model_validate(converted_row()).allowance_percent() == 10


def test_a_price_listed_in_eur_may_carry_a_note_without_gaining_an_allowance():
    assert Price.model_validate(price_row(conversionNote="test remark")).allowance_percent() == 0


@pytest.mark.parametrize("change", [
    {"inputMinorUnitsPerMillionTokens": 0},
    {"outputMinorUnitsPerMillionTokens": 0},
    {"inputMinorUnitsPerMillionTokens": -300},
    {"outputMinorUnitsPerMillionTokens": -1},
    {"inputMinorUnitsPerMillionTokens": 300.5},
    {"verifiedOn": "2026-02-30"},
    {"verifiedOn": "2026-13-01"},
    {"verifiedOn": "11.10.2026"},
    {"verifiedOn": "2026-10-1"},
    {"verifiedOn": "2026-10-01T00:00:00Z"},
    {"verifiedOn": ""},
    {"listCurrency": "usd"},
    {"listCurrency": "US"},
    {"listCurrency": "EURO"},
    {"listCurrency": ""},
    {"listCurrency": "USD", "conversionNote": ""},
    {"listCurrency": "USD", "conversionNote": "   "},
    {"listCurrency": "CHF"},
    {"sourceUrl": "http://example.invalid/test-prices"},
    {"sourceUrl": "example.invalid/test-prices"},
    {"sourceUrl": ""},
    {"currency": "USD"},
    {"model": ""},
    {"provider": ""},
    {"region": ""},
    {"exchangeRate": "1.10"},
])
def test_price_row_refuses(change):
    with pytest.raises(ValidationError):
        Price.model_validate(price_row(**change))


@pytest.mark.parametrize("field", ["model", "provider", "region", "currency", "listCurrency",
                                   "inputMinorUnitsPerMillionTokens", "outputMinorUnitsPerMillionTokens",
                                   "verifiedOn", "sourceUrl"])
def test_price_row_needs_every_field_but_the_note(field):
    with pytest.raises(ValidationError):
        Price.model_validate(without(price_row(), field))


def test_a_price_row_without_a_note_is_a_price_listed_in_eur():
    assert Price.model_validate(without(price_row(), "conversionNote")).conversionNote == ""


# --- the hold for one attempt -------------------------------------------------------------


def test_one_attempt_is_held_at_the_next_whole_cent():
    # 6000 x 300 + 12096 x 1500 = 19,944,000 price units = 19.944 minor units.
    assert attempt_hold_minor_units(Price.model_validate(price_row()), 6000, 12096, 0) == 20


def test_the_allowance_is_added_before_the_amount_is_rounded_up():
    row = Price.model_validate(converted_row())
    # 19.944 x 1.10 = 21.9384.
    assert attempt_hold_minor_units(row, 6000, 12096, 10) == 22
    # 5.1 x 1.10 = 5.61, held as 6. Rounding to 6 first and adding 10 per cent after would hold 7.
    assert attempt_hold_minor_units(row, 2000, 3000, 10) == 6


@pytest.mark.parametrize("input_tokens,output_tokens,plain,with_allowance", [
    (1, 0, 1, 1),                    # 0.0003 minor units still cost a whole one
    (0, 1, 1, 1),
    (1, 1, 1, 1),
    (1_000_000, 0, 300, 330),        # exact amounts are not rounded any further
    (0, 1_000_000, 1500, 1650),
    (1_000_000, 1_000_000, 1800, 1980),
    (3333, 667, 3, 3),               # 2.0004 and 2.20044
    (123_456, 7_890, 49, 54),        # 48.8718 and 53.75898
    (999_999, 1, 301, 331),          # 300.0012 and 330.00132
])
def test_hold_amounts_worked_by_hand(input_tokens, output_tokens, plain, with_allowance):
    row = Price.model_validate(price_row())
    assert attempt_hold_minor_units(row, input_tokens, output_tokens, 0) == plain
    assert attempt_hold_minor_units(row, input_tokens, output_tokens, 10) == with_allowance


@pytest.mark.parametrize("input_tokens,output_tokens,linear_price_units", [
    (1, 1, 1_800),
    (6000, 12096, 19_944_000),
    (3333, 667, 2_000_400),
    (123_456, 7_890, 48_871_800),
    (999_999, 1, 300_001_200),
    (1_000_000, 1_000_000, 1_800_000_000),
])
def test_a_hold_is_never_below_the_linear_cost_and_less_than_a_cent_above_it(
        input_tokens, output_tokens, linear_price_units):
    held = attempt_hold_minor_units(Price.model_validate(price_row()), input_tokens, output_tokens, 0)
    assert held * 1_000_000 >= linear_price_units
    assert (held - 1) * 1_000_000 < linear_price_units


def test_the_smallest_possible_hold_is_one_minor_unit():
    cheapest = Price.model_validate(price_row(inputMinorUnitsPerMillionTokens=1, outputMinorUnitsPerMillionTokens=1))
    assert attempt_hold_minor_units(cheapest, 1, 1, 0) == 1


# --- price lookup and freshness -----------------------------------------------------------


def test_find_price_returns_the_row_for_model_provider_and_region():
    ledger = book(prices=[price_row(), price_row(region="us", outputMinorUnitsPerMillionTokens=1600)])
    assert find_price(ledger, **SELECTOR, today=TODAY).outputMinorUnitsPerMillionTokens == 1500
    assert find_price(ledger, **{**SELECTOR, "region": "us"}, today=TODAY).outputMinorUnitsPerMillionTokens == 1600


@pytest.mark.parametrize("selector", [
    {"model": "other-model", "provider": "test-provider", "region": "eu"},
    {"model": "test-model", "provider": "other-provider", "region": "eu"},
    {"model": "test-model", "provider": "test-provider", "region": "us"},
])
def test_find_price_refuses_a_missing_row(selector):
    with pytest.raises(ValueError, match="no verified price"):
        find_price(book(), **selector, today=TODAY)


def test_find_price_refuses_an_empty_price_table():
    with pytest.raises(ValueError, match="no verified price"):
        find_price(book(prices=[]), **SELECTOR, today=TODAY)


def test_find_price_accepts_a_row_verified_today_and_refuses_one_verified_tomorrow():
    today = book(prices=[price_row(verifiedOn="2026-10-12")])
    assert find_price(today, **SELECTOR, today=TODAY).verifiedOn == "2026-10-12"
    with pytest.raises(ValueError, match="future"):
        find_price(book(prices=[price_row(verifiedOn="2026-10-13")]), **SELECTOR, today=TODAY)


def test_find_price_accepts_a_row_exactly_the_maximum_age_old_and_refuses_one_day_more():
    # 12 September plus 30 days is 12 October.
    ledger = book(maxPriceAgeDays=30, prices=[price_row(verifiedOn="2026-09-12")])
    assert find_price(ledger, **SELECTOR, today=date(2026, 10, 11)).verifiedOn == "2026-09-12"
    assert find_price(ledger, **SELECTOR, today=date(2026, 10, 12)).verifiedOn == "2026-09-12"
    with pytest.raises(ValueError, match="31 days ago"):
        find_price(ledger, **SELECTOR, today=date(2026, 10, 13))


def test_find_price_uses_the_maximum_age_of_the_ledger_it_reads():
    ledger = book(maxPriceAgeDays=7, prices=[price_row(verifiedOn="2026-10-05")])
    assert find_price(ledger, **SELECTOR, today=date(2026, 10, 12)).verifiedOn == "2026-10-05"
    with pytest.raises(ValueError, match="8 days ago"):
        find_price(ledger, **SELECTOR, today=date(2026, 10, 13))


@pytest.mark.parametrize("on,fresh", [
    (date(2026, 9, 11), False),      # the day before verification
    (date(2026, 9, 12), True),       # the day of verification
    (date(2026, 10, 11), True),      # 29 days
    (date(2026, 10, 12), True),      # exactly 30 days
    (date(2026, 10, 13), False),     # 31 days
])
def test_price_is_fresh_from_the_day_of_verification_through_the_maximum_age(on, fresh):
    assert price_is_fresh(Price.model_validate(price_row(verifiedOn="2026-09-12")), on, 30) is fresh


# --- instants -----------------------------------------------------------------------------


def test_an_instant_is_written_in_utc_whole_seconds_with_a_z():
    assert format_instant(NOW) == "2026-10-12T09:00:00Z"
    berlin_summer = datetime(2026, 10, 13, 1, 30, 0, tzinfo=timezone(timedelta(hours=2)))
    assert format_instant(berlin_summer) == "2026-10-12T23:30:00Z"


def test_an_instant_without_a_time_zone_is_refused():
    with pytest.raises(ValueError, match="time zone"):
        format_instant(datetime(2026, 10, 12, 9, 0, 0))


def test_now_utc_is_an_aware_utc_instant_in_whole_seconds():
    instant = now_utc()
    assert instant.utcoffset() == timedelta(0) and instant.microsecond == 0


# --- reserve ------------------------------------------------------------------------------


def test_a_reservation_stores_everything_needed_to_recompute_and_settle_it():
    ledger = book()
    entry = hold(ledger, note="test reservation")
    assert entry.model_dump(exclude_none=True) == reservation_row()
    assert ledger.entries == [entry]
    assert remaining_minor_units(ledger) == 9520


def test_a_reservation_on_a_converted_price_stores_the_allowance_it_was_made_with():
    ledger = book(prices=[converted_row()])
    entry = hold(ledger, note="test reservation")
    assert entry.model_dump(exclude_none=True) == converted_reservation_row()
    assert remaining_minor_units(ledger) == 9472


@pytest.mark.parametrize("attempts,retry_multiplier,amount", [
    (1, 1, 20), (12, 1, 240), (1, 2, 40), (12, 2, 480), (5, 3, 300),
])
def test_a_reservation_is_the_hold_times_attempts_times_the_retry_multiplier(attempts, retry_multiplier, amount):
    entry = hold(book(), attempts=attempts, retry_multiplier=retry_multiplier)
    assert entry.perAttemptMinorUnits == 20
    assert entry.amountMinorUnits == amount


def test_each_attempt_is_rounded_up_before_the_attempts_are_multiplied():
    # 2000 input and 3000 output tokens are 5.1 minor units, held as 6 per attempt:
    # ten attempts hold 60, not the 51 that rounding the sum would give.
    entry = hold(book(), attempts=10, retry_multiplier=1, max_input_tokens=2000, max_output_tokens=3000)
    assert entry.perAttemptMinorUnits == 6
    assert entry.amountMinorUnits == 60


def test_reserve_refuses_a_second_open_reservation_for_the_same_arm():
    ledger = book()
    first = hold(ledger)
    with pytest.raises(ValueError, match="open reservation"):
        hold(ledger, entry_id="res-2", now=LATER)
    assert ledger.entries == [first]
    assert remaining_minor_units(ledger) == 9520


def test_the_same_arm_name_in_another_experiment_reserves_on_its_own():
    ledger = book()
    hold(ledger)
    hold(ledger, entry_id="res-2", experiment_id="other-test-exp", now=LATER)
    assert [entry.id for entry in open_reservations(ledger)] == ["res-1", "res-2"]
    assert remaining_minor_units(ledger) == 9040


def test_an_arm_reserves_again_once_its_reservation_is_closed():
    ledger = book()
    hold(ledger)
    void(ledger, entry_id="void-1", reservation_id="res-1", now=LATER, note="test void")
    hold(ledger, entry_id="res-2", now=LATEST)
    assert [entry.id for entry in open_reservations(ledger)] == ["res-2"]
    assert remaining_minor_units(ledger) == 9520


def test_a_reservation_of_exactly_the_remaining_cap_is_accepted():
    ledger = book(capMinorUnits=480)
    hold(ledger)
    assert remaining_minor_units(ledger) == 0
    assert status(ledger)["capExceeded"] is False


def test_a_reservation_one_unit_above_the_remaining_cap_is_refused_and_changes_nothing():
    ledger = book(capMinorUnits=479)
    with pytest.raises(ValueError, match="480 minor units exceeds the remaining 479"):
        hold(ledger)
    assert ledger.entries == []
    assert remaining_minor_units(ledger) == 479


def test_the_cap_is_cumulative_across_arms():
    # 480 for the first arm leaves 240 of 720: twelve attempts without a retry allowance fit exactly.
    ledger = book(capMinorUnits=720)
    hold(ledger)
    hold(ledger, entry_id="res-2", arm="iteration", retry_multiplier=1, now=LATER)
    assert remaining_minor_units(ledger) == 0
    short = book(capMinorUnits=719)
    first = hold(short)
    with pytest.raises(ValueError, match="240 minor units exceeds the remaining 239"):
        hold(short, entry_id="res-2", arm="iteration", retry_multiplier=1, now=LATER)
    assert short.entries == [first]
    assert remaining_minor_units(short) == 239


def test_nothing_can_be_reserved_once_the_cap_is_used_up():
    ledger = book(capMinorUnits=480)
    hold(ledger)
    with pytest.raises(ValueError, match="exceeds the remaining 0"):
        hold(ledger, entry_id="res-2", arm="iteration", attempts=1, retry_multiplier=1, now=LATER)
    assert len(ledger.entries) == 1


@pytest.mark.parametrize("zero", ["attempts", "max_input_tokens", "max_output_tokens", "retry_multiplier"])
def test_reserve_refuses_a_zero_so_that_no_hold_can_be_zero(zero):
    ledger = book()
    with pytest.raises(ValidationError):
        hold(ledger, **{zero: 0})
    assert ledger.entries == []


@pytest.mark.parametrize("verified_on,message", [
    ("2026-09-11", "31 days ago"),
    ("2026-10-13", "future"),
])
def test_reserve_refuses_a_stale_or_future_price_and_changes_nothing(verified_on, message):
    ledger = book(prices=[price_row(verifiedOn=verified_on)])
    with pytest.raises(ValueError, match=message):
        hold(ledger)
    assert ledger.entries == []


def test_reserve_refuses_a_model_without_a_price_row():
    ledger = book()
    with pytest.raises(ValueError, match="no verified price"):
        hold(ledger, model="other-model")
    assert ledger.entries == []


def test_reserve_reads_the_price_age_on_the_utc_day_of_the_instant():
    # The row is 30 days old through 12 October UTC and 31 days old from midnight.
    ledger = book(prices=[price_row(verifiedOn="2026-09-12")])
    hold(ledger, now=datetime(2026, 10, 12, 23, 59, 59, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="31 days ago"):
        hold(ledger, entry_id="res-2", arm="iteration", now=datetime(2026, 10, 13, 0, 0, 0, tzinfo=timezone.utc))
    # 01:30 on 13 October at UTC+2 is still 12 October in UTC.
    early = book(prices=[price_row(verifiedOn="2026-09-12")])
    entry = hold(early, now=datetime(2026, 10, 13, 1, 30, 0, tzinfo=timezone(timedelta(hours=2))))
    assert entry.recordedAt == "2026-10-12T23:30:00Z"
    # 23:30 on 12 October at UTC-2 is already 13 October in UTC.
    late = book(prices=[price_row(verifiedOn="2026-09-12")])
    with pytest.raises(ValueError, match="31 days ago"):
        hold(late, now=datetime(2026, 10, 12, 23, 30, 0, tzinfo=timezone(timedelta(hours=-2))))
    assert late.entries == []


@pytest.mark.parametrize("change", [
    {"preregistration_sha256": "not-a-hash"},
    {"preregistration_sha256": "A" * 64},
    {"entry_id": "Res 1"},
    {"entry_id": "r1"},
    {"now": datetime(2026, 10, 12, 9, 0, 0)},
    {"experiment_id": ""},
    {"arm": ""},
])
def test_reserve_refuses_a_malformed_entry_and_changes_nothing(change):
    ledger = book()
    with pytest.raises(ValueError):
        hold(ledger, **change)
    assert ledger.entries == []


def test_reserve_refuses_an_id_already_in_the_ledger():
    ledger = book()
    first = hold(ledger)
    with pytest.raises(ValueError, match="unique"):
        hold(ledger, entry_id="res-1", arm="iteration", now=LATER)
    assert ledger.entries == [first]


def test_reserve_refuses_an_instant_before_the_last_entry():
    ledger = book()
    first = hold(ledger, now=LATER)
    with pytest.raises(ValueError, match="dated before"):
        hold(ledger, entry_id="res-2", arm="iteration", now=NOW)
    assert ledger.entries == [first]


# --- entry validation by kind -------------------------------------------------------------


def test_the_hand_written_rows_are_valid_entries():
    assert Entry.model_validate(reservation_row()).amountMinorUnits == 480
    assert Entry.model_validate(converted_reservation_row()).amountMinorUnits == 528
    assert Entry.model_validate(settlement_row()).reservationId == "res-1"
    assert Entry.model_validate(void_row()).amountMinorUnits == 0


@pytest.mark.parametrize("field", sorted(HOLD_FIELDS))
def test_a_reservation_missing_a_hold_field_is_refused(field):
    with pytest.raises(ValidationError, match=f"a reservation records {field}"):
        Entry.model_validate(without(reservation_row(), field))


@pytest.mark.parametrize("change", [
    {"perAttemptMinorUnits": 19},
    {"perAttemptMinorUnits": 21},
    {"perAttemptMinorUnits": 21, "amountMinorUnits": 504},     # consistent with itself, not with the price
    {"perAttemptMinorUnits": 22, "amountMinorUnits": 528},     # the converted figures on a price in EUR
    {"maxOutputTokensPerAttempt": 13000},                      # 21.3 minor units, held as 22
    {"maxInputTokensPerAttempt": 10000},                       # 21.144 minor units, held as 22
    {"price": price_row(outputMinorUnitsPerMillionTokens=1600)},
])
def test_a_reservation_whose_per_attempt_amount_does_not_follow_from_its_price_is_refused(change):
    with pytest.raises(ValidationError, match="per-attempt amount does not follow"):
        Entry.model_validate(reservation_row(**change))


@pytest.mark.parametrize("change", [
    {"amountMinorUnits": 479},
    {"amountMinorUnits": 481},
    {"amountMinorUnits": 240},
    {"amountMinorUnits": 20},
    {"amountMinorUnits": 0},
    {"attempts": 11},
    {"retryMultiplier": 1},
])
def test_a_reservation_whose_total_does_not_follow_from_its_parts_is_refused(change):
    with pytest.raises(ValidationError, match="reservation amount does not follow"):
        Entry.model_validate(reservation_row(**change))


def test_a_reservation_with_an_allowance_on_a_price_listed_in_eur_is_refused():
    with pytest.raises(ValidationError, match="no conversion allowance"):
        Entry.model_validate(converted_reservation_row(price=price_row()))


def test_a_reservation_on_a_converted_price_without_its_allowance_in_the_amounts_is_refused():
    with pytest.raises(ValidationError, match="per-attempt amount does not follow"):
        Entry.model_validate(converted_reservation_row(perAttemptMinorUnits=20, amountMinorUnits=480))


@pytest.mark.parametrize("field,value", [("reservationId", "res-0"), *EVIDENCE_FIELDS.items()])
def test_a_reservation_carrying_a_closure_field_is_refused(field, value):
    with pytest.raises(ValidationError, match="does not close another entry"):
        Entry.model_validate(reservation_row(**{field: value}))


@pytest.mark.parametrize("change", [
    # Zero token maxima with the amounts that would follow from them: 18.144 held as 19, 1.8 held as 2.
    {"maxInputTokensPerAttempt": 0, "perAttemptMinorUnits": 19, "amountMinorUnits": 456},
    {"maxOutputTokensPerAttempt": 0, "perAttemptMinorUnits": 2, "amountMinorUnits": 48},
    {"retryMultiplier": 0, "amountMinorUnits": 0},
    {"perAttemptMinorUnits": 0, "amountMinorUnits": 0},
    {"attempts": 0, "amountMinorUnits": 0},
    {"amountMinorUnits": -480},
    {"conversionAllowancePercent": -1},
    {"conversionAllowancePercent": 101},
    {"preregistrationSha256": "c" * 63},
    {"id": "Res-1"},
    {"id": "r1"},
    {"id": "-res-1"},
    {"kind": "REFUND"},
    {"experimentId": ""},
    {"arm": ""},
    {"overrunMinorUnits": 1},
])
def test_entry_refuses_a_malformed_reservation(change):
    with pytest.raises(ValidationError):
        Entry.model_validate(reservation_row(**change))


@pytest.mark.parametrize("recorded_at", [
    "2026-10-12T09:00:00+00:00",
    "2026-10-12T11:00:00+02:00",
    "2026-10-12T09:00:00",
    "2026-10-12",
    "2026-10-12 09:00:00Z",
    "2026-10-12T09:00:00.000Z",
    "2026-10-12T09:00Z",
    "20261012T090000Z",
    "2026-10-12T09:00:00z",
    "12.10.2026 09:00",
    "",
])
@pytest.mark.parametrize("row", [reservation_row, settlement_row, void_row])
def test_recorded_at_is_refused_in_any_spelling_but_the_utc_one(row, recorded_at):
    with pytest.raises(ValidationError, match="recordedAt is a UTC instant|ISO 8601|time zone"):
        Entry.model_validate(row(recordedAt=recorded_at))


@pytest.mark.parametrize("row", [settlement_row, void_row])
@pytest.mark.parametrize("field", sorted(HOLD_FIELDS))
def test_a_closure_carrying_a_hold_field_is_refused(row, field):
    with pytest.raises(ValidationError, match="only a reservation records"):
        Entry.model_validate(row(**{field: HOLD_FIELDS[field]}))


@pytest.mark.parametrize("row,kind", [(settlement_row, "settlement"), (void_row, "void")])
def test_a_closure_that_names_no_reservation_is_refused(row, kind):
    with pytest.raises(ValidationError, match=f"a {kind} names the reservation it closes"):
        Entry.model_validate(without(row(), "reservationId"))


@pytest.mark.parametrize("amount", [1, 123, 480])
def test_a_void_with_an_amount_is_refused(amount):
    with pytest.raises(ValidationError, match="releases the whole reservation"):
        Entry.model_validate(void_row(amountMinorUnits=amount))


@pytest.mark.parametrize("field", sorted(EVIDENCE_FIELDS))
def test_a_void_carrying_an_evidence_field_is_refused(field):
    with pytest.raises(ValidationError, match="no attempts to settle"):
        Entry.model_validate(void_row(**{field: EVIDENCE_FIELDS[field]}))


@pytest.mark.parametrize("field", sorted(EVIDENCE_FIELDS))
def test_a_settlement_missing_an_evidence_field_is_refused(field):
    with pytest.raises(ValidationError, match=f"a settlement records {field}"):
        Entry.model_validate(without(settlement_row(), field))


@pytest.mark.parametrize("observed,silent", [(12, 13), (0, 1), (5, 12)])
def test_a_settlement_with_more_silent_than_observed_attempts_is_refused(observed, silent):
    with pytest.raises(ValidationError, match="share of the observed attempts"):
        Entry.model_validate(settlement_row(observedAttempts=observed, attemptsWithoutUsage=silent))


@pytest.mark.parametrize("observed,silent", [(12, 12), (0, 0), (12, 0), (1, 1)])
def test_a_settlement_may_have_every_observed_attempt_silent(observed, silent):
    entry = Entry.model_validate(settlement_row(observedAttempts=observed, attemptsWithoutUsage=silent))
    assert (entry.observedAttempts, entry.attemptsWithoutUsage) == (observed, silent)


@pytest.mark.parametrize("change", [
    {"evidenceSha256": "not-a-hash"},
    {"evidenceSha256": "B" * 64},
    {"observedAttempts": -1},
    {"attemptsWithoutUsage": -1},
    {"amountMinorUnits": -1},
    {"attempts": 0},
])
def test_entry_refuses_a_malformed_settlement(change):
    with pytest.raises(ValidationError):
        Entry.model_validate(settlement_row(**change))


def test_a_settlement_of_zero_is_a_valid_entry():
    assert Entry.model_validate(settlement_row(amountMinorUnits=0, observedAttempts=0)).amountMinorUnits == 0


# --- the ledger as a history --------------------------------------------------------------


def test_a_reservation_and_its_settlement_load_and_free_the_difference():
    ledger = book(entries=[reservation_row(), settlement_row()])
    assert committed_minor_units(ledger) == 123
    assert remaining_minor_units(ledger) == 9877


def test_a_reservation_and_its_void_load_and_free_the_whole_hold():
    ledger = book(entries=[reservation_row(), void_row()])
    assert committed_minor_units(ledger) == 0
    assert remaining_minor_units(ledger) == 10000


@pytest.mark.parametrize("entries", [
    [reservation_row(), reservation_row(arm="iteration", recordedAt="2026-10-12T10:00:00Z")],
    [reservation_row(), settlement_row(id="res-1")],
    [reservation_row(), settlement_row(),
     void_row(id="set-1", reservationId="res-1", recordedAt="2026-10-12T11:00:00Z")],
])
def test_ledger_refuses_two_entries_with_one_id(entries):
    with pytest.raises(ValidationError, match="unique"):
        book(entries=entries)


@pytest.mark.parametrize("entries", [
    [reservation_row(recordedAt="2026-10-12T10:00:00Z"), settlement_row(recordedAt="2026-10-12T09:59:59Z")],
    [reservation_row(recordedAt="2026-10-12T10:00:00Z"), void_row(recordedAt="2026-10-11T10:00:01Z")],
    [reservation_row(recordedAt="2026-10-12T10:00:00Z"),
     reservation_row(id="res-2", arm="iteration", recordedAt="2026-10-12T09:00:00Z")],
    [reservation_row(), settlement_row(recordedAt="2020-01-01T00:00:00Z")],
])
def test_ledger_refuses_an_entry_dated_before_the_entry_above_it(entries):
    with pytest.raises(ValidationError, match="dated before the entry above it"):
        book(entries=entries)


def test_ledger_accepts_two_entries_written_in_the_same_second():
    ledger = book(entries=[reservation_row(), settlement_row(recordedAt="2026-10-12T09:00:00Z")])
    assert remaining_minor_units(ledger) == 9877


@pytest.mark.parametrize("closure", [
    settlement_row(recordedAt="2026-10-12T08:00:00Z"),
    void_row(recordedAt="2026-10-12T08:00:00Z"),
])
def test_ledger_refuses_a_closure_listed_before_its_reservation(closure):
    with pytest.raises(ValidationError, match="does not close an earlier reservation"):
        book(entries=[closure, reservation_row()])


@pytest.mark.parametrize("closure", [
    settlement_row(reservationId="res-9"),
    void_row(reservationId="res-9"),
    settlement_row(reservationId=""),
    settlement_row(reservationId="set-1"),
])
def test_ledger_refuses_a_closure_of_a_reservation_that_does_not_exist(closure):
    with pytest.raises(ValidationError, match="does not close an earlier reservation"):
        book(entries=[reservation_row(), closure])


@pytest.mark.parametrize("closure", [
    settlement_row(arm="iteration"),
    settlement_row(experimentId="other-test-exp"),
    void_row(arm="iteration"),
    void_row(experimentId="other-test-exp"),
])
def test_ledger_refuses_a_closure_for_another_arm_or_experiment(closure):
    with pytest.raises(ValidationError, match="of the same arm"):
        book(entries=[reservation_row(), closure])


def test_ledger_refuses_a_closure_that_names_the_reservation_of_another_arm():
    other = reservation_row(id="res-2", arm="iteration", recordedAt="2026-10-12T09:30:00Z")
    with pytest.raises(ValidationError, match="of the same arm"):
        book(entries=[reservation_row(), other, settlement_row(arm="iteration")])


@pytest.mark.parametrize("first,second", [
    (settlement_row(), settlement_row(id="set-2", recordedAt="2026-10-12T11:00:00Z")),
    (settlement_row(), void_row(recordedAt="2026-10-12T11:00:00Z")),
    (void_row(), void_row(id="void-2", recordedAt="2026-10-12T11:00:00Z")),
    (void_row(), settlement_row(recordedAt="2026-10-12T11:00:00Z")),
])
def test_ledger_refuses_a_reservation_closed_twice(first, second):
    with pytest.raises(ValidationError, match="closed twice"):
        book(entries=[reservation_row(), first, second])


def test_ledger_refuses_two_open_reservations_for_one_arm():
    with pytest.raises(ValidationError, match="two open reservations"):
        book(entries=[reservation_row(), reservation_row(id="res-2", recordedAt="2026-10-12T10:00:00Z")])


def test_ledger_accepts_a_second_reservation_for_an_arm_whose_first_one_is_closed():
    ledger = book(entries=[reservation_row(), void_row(),
                           reservation_row(id="res-2", recordedAt="2026-10-12T11:00:00Z")])
    assert [entry.id for entry in open_reservations(ledger)] == ["res-2"]
    assert remaining_minor_units(ledger) == 9520


def test_ledger_accepts_open_reservations_for_two_arms_and_for_one_arm_name_in_two_experiments():
    ledger = book(entries=[
        reservation_row(),
        reservation_row(id="res-2", arm="iteration", recordedAt="2026-10-12T09:10:00Z"),
        reservation_row(id="res-3", experimentId="other-test-exp", recordedAt="2026-10-12T09:20:00Z")])
    assert remaining_minor_units(ledger) == 8560


def test_ledger_refuses_a_settlement_that_observes_more_attempts_than_were_reserved():
    # Twelve attempts were reserved. The retry multiplier of 2 widens the amount, not the count.
    with pytest.raises(ValidationError, match="more attempts than its reservation covers"):
        book(entries=[reservation_row(), settlement_row(observedAttempts=13)])
    assert book(entries=[reservation_row(), settlement_row(observedAttempts=12)]).entries[1].observedAttempts == 12


def test_ledger_accepts_a_reservation_that_uses_the_cap_exactly_and_refuses_one_unit_more():
    assert remaining_minor_units(book(capMinorUnits=480, entries=[reservation_row()])) == 0
    with pytest.raises(ValidationError, match="reservation res-1 takes committed spend past the cap"):
        book(capMinorUnits=479, entries=[reservation_row()])


def test_ledger_adds_up_open_reservations_against_the_cap():
    second = reservation_row(id="res-2", arm="iteration", retryMultiplier=1, amountMinorUnits=240,
                             recordedAt="2026-10-12T09:30:00Z")
    assert remaining_minor_units(book(capMinorUnits=720, entries=[reservation_row(), second])) == 0
    with pytest.raises(ValidationError, match="reservation res-2 takes committed spend past the cap"):
        book(capMinorUnits=719, entries=[reservation_row(), second])


def test_a_closed_reservation_frees_room_for_the_next_one():
    second = reservation_row(id="res-2", arm="iteration", recordedAt="2026-10-12T11:00:00Z")
    with pytest.raises(ValidationError, match="past the cap"):
        book(capMinorUnits=600, entries=[reservation_row(), second])
    # Settled at 100, the first arm leaves 500 of 600 and the second hold of 480 fits.
    settled = book(capMinorUnits=600, entries=[reservation_row(), settlement_row(amountMinorUnits=100), second])
    assert remaining_minor_units(settled) == 20
    # Settled at 121 it leaves 479, one unit short.
    with pytest.raises(ValidationError, match="reservation res-2 takes committed spend past the cap"):
        book(capMinorUnits=600, entries=[reservation_row(), settlement_row(amountMinorUnits=121), second])
    voided = book(capMinorUnits=480, entries=[reservation_row(), void_row(), second])
    assert remaining_minor_units(voided) == 0


def test_a_settlement_above_its_reservation_is_recorded_and_reported():
    ledger = book(entries=[reservation_row(), settlement_row(amountMinorUnits=481)])
    state = status(ledger)
    assert state["settlementsAboveTheirReservation"] == {"set-1": 1}
    assert state["settledMinorUnits"] == 481
    assert state["remainingMinorUnits"] == 9519
    assert state["capExceeded"] is False


@pytest.mark.parametrize("amount", [480, 479, 0])
def test_a_settlement_at_or_below_its_reservation_is_not_reported_as_an_overrun(amount):
    ledger = book(entries=[reservation_row(), settlement_row(amountMinorUnits=amount)])
    assert status(ledger)["settlementsAboveTheirReservation"] == {}


def test_a_settlement_past_the_cap_is_recorded_and_the_breach_is_reported():
    ledger = book(capMinorUnits=500, entries=[reservation_row(), settlement_row(amountMinorUnits=520)])
    state = status(ledger)
    assert state["settledMinorUnits"] == 520
    assert state["openReservationMinorUnits"] == 0
    assert state["remainingMinorUnits"] == -20
    assert state["capExceeded"] is True
    assert state["settlementsAboveTheirReservation"] == {"set-1": 40}


def test_a_settlement_that_lands_exactly_on_the_cap_does_not_exceed_it():
    ledger = book(capMinorUnits=500, entries=[reservation_row(), settlement_row(amountMinorUnits=500)])
    state = status(ledger)
    assert state["remainingMinorUnits"] == 0 and state["capExceeded"] is False
    assert state["settlementsAboveTheirReservation"] == {"set-1": 20}


def test_no_reservation_is_accepted_after_a_settlement_took_spend_past_the_cap():
    breach = [reservation_row(), settlement_row(amountMinorUnits=520)]
    smallest = reservation_row(id="res-2", arm="iteration", attempts=1, retryMultiplier=1, amountMinorUnits=20,
                               recordedAt="2026-10-12T11:00:00Z")
    with pytest.raises(ValidationError, match="reservation res-2 takes committed spend past the cap"):
        book(capMinorUnits=500, entries=[*breach, smallest])
    ledger = book(capMinorUnits=500, entries=breach)
    with pytest.raises(ValueError, match="exceeds the remaining -20"):
        hold(ledger, entry_id="res-2", arm="iteration", attempts=1, retry_multiplier=1, now=LATEST)
    assert len(ledger.entries) == 2


def test_ledger_refuses_two_price_rows_for_one_model_provider_and_region():
    with pytest.raises(ValidationError, match="one price row per model, provider and region"):
        book(prices=[price_row(), price_row(verifiedOn="2026-10-05", outputMinorUnitsPerMillionTokens=1600)])


@pytest.mark.parametrize("other", [{"model": "other-model"}, {"provider": "other-provider"}, {"region": "us"}])
def test_ledger_accepts_price_rows_that_differ_in_model_provider_or_region(other):
    assert len(book(prices=[price_row(), price_row(**other)]).prices) == 2


@pytest.mark.parametrize("change", [
    {"schema": "mycounsel.spend-ledger.v2"},
    {"currency": "USD"},
    {"capMinorUnits": 0},
    {"capMinorUnits": -10000},
    {"capMinorUnits": 100.5},
    {"maxPriceAgeDays": 0},
    {"maxPriceAgeDays": 91},
    {"resetOn": "2026-11-01"},
])
def test_ledger_refuses_a_malformed_header(change):
    with pytest.raises(ValidationError):
        book(**change)


def test_the_price_age_limit_defaults_to_thirty_days_and_runs_from_one_to_ninety():
    assert book().maxPriceAgeDays == 30
    assert book(maxPriceAgeDays=1).maxPriceAgeDays == 1
    assert book(maxPriceAgeDays=90).maxPriceAgeDays == 90


# --- settlement estimate ------------------------------------------------------------------


def test_one_reported_attempt_is_rounded_up_to_a_whole_cent():
    reservation = Entry.model_validate(reservation_row())
    assert settlement_minor_units(reservation, [(2000, 3000)]) == estimate(6)


def test_reported_usage_is_summed_and_rounded_up_once():
    # Two attempts of 5.1 minor units are 10.2, settled at 11. Rounding each would give 12.
    reservation = Entry.model_validate(reservation_row())
    assert settlement_minor_units(reservation, [(2000, 3000), (2000, 3000)]) == estimate(11)


def test_an_attempt_without_usage_is_charged_its_full_hold():
    reservation = Entry.model_validate(reservation_row())
    assert settlement_minor_units(reservation, [None]) == estimate(20, silent=1)
    assert settlement_minor_units(reservation, [(2000, 3000), None]) == estimate(26, silent=1)
    assert settlement_minor_units(reservation, [None, None, None]) == estimate(60, silent=3)


def test_an_attempt_reporting_zero_input_tokens_is_charged_its_full_hold():
    # As reported, 3000 output tokens alone would be 4.5 minor units. No real call has an empty input.
    reservation = Entry.model_validate(reservation_row())
    assert settlement_minor_units(reservation, [(0, 3000)]) == estimate(20, silent=1)
    assert settlement_minor_units(reservation, [(0, 0)]) == estimate(20, silent=1)
    assert settlement_minor_units(reservation, [(0, 3000), (2000, 3000)]) == estimate(26, silent=1)


def test_an_attempt_reporting_input_but_no_output_is_charged_as_reported():
    # 2000 input tokens are 0.6 minor units.
    reservation = Entry.model_validate(reservation_row())
    assert settlement_minor_units(reservation, [(2000, 0)]) == estimate(1)


def test_no_observed_attempt_costs_nothing():
    reservation = Entry.model_validate(reservation_row())
    assert settlement_minor_units(reservation, []) == estimate(0)


def test_usage_exactly_at_the_reserved_maxima_is_not_counted_as_above_them():
    reservation = Entry.model_validate(reservation_row())
    assert settlement_minor_units(reservation, [(6000, 12096)]) == estimate(20)
    assert settlement_minor_units(reservation, [(5999, 12095)]) == estimate(20)


@pytest.mark.parametrize("usage,amount", [
    ((6001, 12096), 20),             # 19.9443
    ((6000, 12097), 20),             # 19.9455
    ((40000, 12096), 31),            # 12,000,000 + 18,144,000 = 30.144
    ((6000, 30000), 47),             # 1,800,000 + 45,000,000 = 46.8
    ((40000, 30000), 57),            # 12,000,000 + 45,000,000 = 57 exactly
])
def test_usage_above_a_reserved_maximum_is_charged_as_reported_and_counted(usage, amount):
    reservation = Entry.model_validate(reservation_row())
    assert settlement_minor_units(reservation, [usage]) == estimate(amount, above=1)


def test_a_mixed_arm_is_summed_once_with_silent_attempts_on_top():
    # Reported: 19,944,000 + 19,944,300 + 19,945,500 = 59.8338, settled at 60. Two silent attempts add 40.
    reservation = Entry.model_validate(reservation_row())
    usages = [(6000, 12096), (6001, 12096), (6000, 12097), None, (0, 3000)]
    assert settlement_minor_units(reservation, usages) == estimate(100, silent=2, above=2)


def test_an_under_reserved_arm_settles_above_its_reservation():
    # Two attempts without a retry allowance hold 40. Both report 40000 input tokens: 60.288, settled at 61.
    reservation = Entry.model_validate(reservation_row(attempts=2, retryMultiplier=1, amountMinorUnits=40))
    assert settlement_minor_units(reservation, [(40000, 12096)] * 2) == estimate(61, above=2)


def test_twelve_attempts_at_the_reserved_maxima_settle_within_a_reservation_without_retry_allowance():
    # 12 x 19.944 = 239.328, settled at 240, which is the whole reservation of 12 x 20.
    reservation = Entry.model_validate(reservation_row(retryMultiplier=1, amountMinorUnits=240))
    settled = settlement_minor_units(reservation, [(6000, 12096)] * 12)
    assert settled == estimate(240)
    assert settled["amountMinorUnits"] <= reservation.amountMinorUnits


def test_twelve_silent_attempts_settle_at_exactly_the_reservation_without_retry_allowance():
    reservation = Entry.model_validate(reservation_row(retryMultiplier=1, amountMinorUnits=240))
    assert settlement_minor_units(reservation, [None] * 12) == estimate(240, silent=12)
    converted = Entry.model_validate(converted_reservation_row(retryMultiplier=1, amountMinorUnits=264))
    assert settlement_minor_units(converted, [None] * 12) == estimate(264, silent=12)


def test_the_stored_allowance_is_applied_to_reported_usage():
    reservation = Entry.model_validate(converted_reservation_row())
    # One million input tokens cost 300, plus 10 per cent.
    assert settlement_minor_units(reservation, [(1_000_000, 0)]) == estimate(330, above=1)
    # 10.2 x 1.10 = 11.22.
    assert settlement_minor_units(reservation, [(2000, 3000), (2000, 3000)]) == estimate(12)
    # 12 x 19.944 x 1.10 = 263.2608.
    assert settlement_minor_units(reservation, [(6000, 12096)] * 12) == estimate(264)


def test_the_stored_allowance_is_part_of_the_hold_charged_for_a_silent_attempt():
    reservation = Entry.model_validate(converted_reservation_row())
    assert settlement_minor_units(reservation, [None, (0, 3000)]) == estimate(44, silent=2)


def test_a_settlement_uses_the_price_stored_with_the_reservation_not_the_current_row():
    # The file's price row was raised to 9000 after the reservation was made at 1500.
    ledger = book(prices=[price_row(outputMinorUnitsPerMillionTokens=9000, verifiedOn="2026-10-11")],
                  entries=[reservation_row()])
    assert ledger.prices[0].outputMinorUnitsPerMillionTokens == 9000
    # 6000 x 300 + 6000 x 1500 = 10.8 at the reserved price; the new row would give 55.8.
    assert settlement_minor_units(ledger.entries[0], [(6000, 6000)]) == estimate(11)
    assert settlement_minor_units(ledger.entries[0], [None]) == estimate(20, silent=1)


@pytest.mark.parametrize("row", [settlement_row, void_row])
def test_only_a_reservation_can_be_settled(row):
    with pytest.raises(ValueError, match="only a reservation can be settled"):
        settlement_minor_units(Entry.model_validate(row()), [(2000, 3000)])


# --- the stored allowance and the module constant -----------------------------------------


def test_a_stored_allowance_survives_a_later_change_of_the_module_constant(monkeypatch, tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger_file(prices=[converted_row()], entries=[converted_reservation_row()])),
                    encoding="utf-8")
    monkeypatch.setattr(candidate_budget, "CONVERSION_ALLOWANCE_PERCENT", 15)
    assert Price.model_validate(converted_row()).allowance_percent() == 15

    ledger = load_ledger(path)
    stored = ledger.entries[0]
    assert (stored.conversionAllowancePercent, stored.perAttemptMinorUnits, stored.amountMinorUnits) == (10, 22, 528)
    # 300 plus the stored 10 per cent, not the 345 the new constant would give.
    assert settlement_minor_units(stored, [(1_000_000, 0)]) == estimate(330, above=1)
    assert settlement_minor_units(stored, [None]) == estimate(22, silent=1)
    settle(ledger, entry_id="set-1", reservation_id="res-1", amount_minor_units=330, observed_attempts=1,
           attempts_without_usage=0, evidence_sha256=EVIDENCE, now=LATER)
    assert remaining_minor_units(ledger) == 9670
    save_ledger(ledger, path)
    assert load_ledger(path).entries[0].conversionAllowancePercent == 10


def test_a_new_reservation_stores_the_constant_in_force_when_it_is_made(monkeypatch):
    ledger = book(prices=[converted_row()], entries=[converted_reservation_row()])
    monkeypatch.setattr(candidate_budget, "CONVERSION_ALLOWANCE_PERCENT", 15)
    # 19.944 x 1.15 = 22.9356, held as 23; 23 x 12 x 2 = 552.
    fresh = hold(ledger, entry_id="res-2", arm="iteration", now=LATER)
    assert (fresh.conversionAllowancePercent, fresh.perAttemptMinorUnits, fresh.amountMinorUnits) == (15, 23, 552)
    assert ledger.entries[0].conversionAllowancePercent == 10
    assert remaining_minor_units(ledger) == 8920


def test_a_price_listed_in_eur_stays_without_allowance_whatever_the_constant(monkeypatch):
    monkeypatch.setattr(candidate_budget, "CONVERSION_ALLOWANCE_PERCENT", 15)
    entry = hold(book())
    assert (entry.conversionAllowancePercent, entry.perAttemptMinorUnits) == (0, 20)


# --- set_price ----------------------------------------------------------------------------


def test_set_price_adds_the_first_row():
    ledger = book(prices=[])
    set_price(ledger, Price.model_validate(price_row()))
    assert [row.model_dump() for row in ledger.prices] == [price_row()]


def test_set_price_refreshes_a_row_and_keeps_one_row_per_key():
    ledger = book(prices=[price_row(), price_row(region="us")])
    set_price(ledger, Price.model_validate(price_row(outputMinorUnitsPerMillionTokens=1600, verifiedOn="2026-10-11")))
    assert len(ledger.prices) == 2
    assert sorted((row.region, row.outputMinorUnitsPerMillionTokens, row.verifiedOn) for row in ledger.prices) == [
        ("eu", 1600, "2026-10-11"), ("us", 1500, "2026-10-01")]
    assert find_price(ledger, **SELECTOR, today=TODAY).outputMinorUnitsPerMillionTokens == 1600


@pytest.mark.parametrize("other", [{"model": "other-model"}, {"provider": "other-provider"}, {"region": "us"}])
def test_set_price_adds_a_row_beside_one_that_differs_in_model_provider_or_region(other):
    ledger = book()
    set_price(ledger, Price.model_validate(price_row(**other)))
    assert len(ledger.prices) == 2


@pytest.mark.parametrize("change", [
    {"inputMinorUnitsPerMillionTokens": 301},
    {"inputMinorUnitsPerMillionTokens": 299},
    {"outputMinorUnitsPerMillionTokens": 9000},
    {"listCurrency": "USD", "conversionNote": TEST_NOTE},
])
def test_set_price_refuses_other_figures_while_a_reservation_at_the_old_ones_is_open(change):
    ledger = book()
    hold(ledger)
    with pytest.raises(ValueError, match="reservation res-1 is open at the old price"):
        set_price(ledger, Price.model_validate(price_row(verifiedOn="2026-10-11", **change)))
    assert [row.model_dump() for row in ledger.prices] == [price_row()]


def test_set_price_allows_other_figures_once_the_reservation_is_settled():
    ledger = book()
    reservation = hold(ledger)
    close(ledger)
    set_price(ledger, Price.model_validate(price_row(outputMinorUnitsPerMillionTokens=9000, verifiedOn="2026-10-11")))
    assert [row.outputMinorUnitsPerMillionTokens for row in ledger.prices] == [9000]
    assert reservation.price.outputMinorUnitsPerMillionTokens == 1500


def test_set_price_allows_other_figures_once_the_reservation_is_voided():
    ledger = book()
    hold(ledger)
    void(ledger, entry_id="void-1", reservation_id="res-1", now=LATER)
    set_price(ledger, Price.model_validate(price_row(inputMinorUnitsPerMillionTokens=450, verifiedOn="2026-10-11")))
    assert [row.inputMinorUnitsPerMillionTokens for row in ledger.prices] == [450]
    # A new hold is made at the new row: 6000 x 450 + 18,144,000 = 20.844, held as 21.
    assert hold(ledger, entry_id="res-2", now=LATEST).perAttemptMinorUnits == 21


def test_set_price_allows_a_refresh_at_unchanged_figures_while_a_reservation_is_open():
    ledger = book()
    reservation = hold(ledger)
    set_price(ledger, Price.model_validate(price_row(verifiedOn="2026-10-11",
                                                     sourceUrl="https://example.invalid/test-prices-reread")))
    assert [row.verifiedOn for row in ledger.prices] == ["2026-10-11"]
    assert reservation.price.verifiedOn == "2026-10-01"
    assert ledger.entries[0].price.sourceUrl == "https://example.invalid/test-prices"


def test_set_price_is_not_held_back_by_an_open_reservation_for_another_row():
    ledger = book(prices=[price_row(), price_row(model="other-model")])
    hold(ledger)
    set_price(ledger, Price.model_validate(price_row(model="other-model", outputMinorUnitsPerMillionTokens=9000)))
    assert sorted((row.model, row.outputMinorUnitsPerMillionTokens) for row in ledger.prices) == [
        ("other-model", 9000), ("test-model", 1500)]


# --- settle and void ----------------------------------------------------------------------


def test_settle_closes_exactly_the_named_reservation():
    ledger = book()
    hold(ledger)
    hold(ledger, entry_id="res-2", arm="iteration")
    entry = close(ledger, observed_attempts=11, attempts_without_usage=2, note="test settlement")
    assert entry.model_dump(exclude_none=True) == settlement_row(observedAttempts=11, attemptsWithoutUsage=2)
    assert [reservation.id for reservation in open_reservations(ledger)] == ["res-2"]
    assert closure_of(ledger, "res-1") == entry
    assert closure_of(ledger, "res-2") is None
    assert remaining_minor_units(ledger) == 9397


def test_void_closes_exactly_the_named_reservation_at_no_cost():
    ledger = book()
    hold(ledger)
    hold(ledger, entry_id="res-2", arm="iteration")
    entry = void(ledger, entry_id="void-1", reservation_id="res-2", now=LATER, note="test void, nothing was dispatched")
    assert entry.model_dump(exclude_none=True) == void_row(arm="iteration", reservationId="res-2")
    assert [reservation.id for reservation in open_reservations(ledger)] == ["res-1"]
    assert closure_of(ledger, "res-2") == entry
    assert remaining_minor_units(ledger) == 9520


def test_a_closure_copies_experiment_arm_and_attempts_from_its_reservation():
    ledger = book()
    hold(ledger, entry_id="res-7", arm="iteration", experiment_id="other-test-exp", attempts=5)
    entry = close(ledger, entry_id="set-7", reservation_id="res-7", observed_attempts=5)
    assert (entry.experimentId, entry.arm, entry.attempts, entry.reservationId) == (
        "other-test-exp", "iteration", 5, "res-7")


@pytest.mark.parametrize("reservation_id", ["res-1", "res-2", "res-9", "set-1", "void-2"])
def test_a_closed_or_unknown_reservation_cannot_be_settled_or_voided(reservation_id):
    ledger = book()
    hold(ledger)
    hold(ledger, entry_id="res-2", arm="iteration")
    hold(ledger, entry_id="res-3", arm="third")
    close(ledger)
    void(ledger, entry_id="void-2", reservation_id="res-2", now=LATER)
    with pytest.raises(ValueError, match=f"no open reservation {reservation_id}"):
        close(ledger, entry_id="set-9", reservation_id=reservation_id, now=LATEST)
    with pytest.raises(ValueError, match=f"no open reservation {reservation_id}"):
        void(ledger, entry_id="void-9", reservation_id=reservation_id, now=LATEST)
    assert [entry.id for entry in ledger.entries] == ["res-1", "res-2", "res-3", "set-1", "void-2"]
    assert [entry.id for entry in open_reservations(ledger)] == ["res-3"]


@pytest.mark.parametrize("change", [
    {"observed_attempts": 13},
    {"observed_attempts": 5, "attempts_without_usage": 6},
    {"evidence_sha256": "not-a-hash"},
    {"amount_minor_units": -1},
    {"entry_id": "res-1"},
    {"entry_id": "Set 1"},
    {"now": datetime(2026, 10, 12, 8, 59, 59, tzinfo=timezone.utc)},
    {"now": datetime(2026, 10, 12, 10, 0, 0)},
])
def test_settle_refuses_a_malformed_settlement_and_leaves_the_reservation_open(change):
    ledger = book()
    first = hold(ledger)
    with pytest.raises(ValueError):
        close(ledger, **change)
    assert ledger.entries == [first]
    assert remaining_minor_units(ledger) == 9520


@pytest.mark.parametrize("change", [
    {"entry_id": "res-1"},
    {"now": datetime(2026, 10, 12, 8, 59, 59, tzinfo=timezone.utc)},
    {"now": datetime(2026, 10, 12, 10, 0, 0)},
])
def test_void_refuses_a_malformed_void_and_leaves_the_reservation_open(change):
    ledger = book()
    first = hold(ledger)
    args = {"entry_id": "void-1", "reservation_id": "res-1", "now": LATER, **change}
    with pytest.raises(ValueError):
        void(ledger, **args)
    assert ledger.entries == [first]


def test_settle_records_an_amount_above_the_reservation_and_past_the_cap():
    ledger = book(capMinorUnits=500)
    hold(ledger)
    close(ledger, amount_minor_units=520)
    state = status(ledger)
    assert state["remainingMinorUnits"] == -20 and state["capExceeded"] is True
    assert state["settlementsAboveTheirReservation"] == {"set-1": 40}


def test_status_of_a_ledger_with_one_settled_one_voided_and_one_open_reservation():
    ledger = book()
    hold(ledger, entry_id="res-a", arm="baseline")                                 # 480
    hold(ledger, entry_id="res-b", arm="iteration")                                # 480
    hold(ledger, entry_id="res-c", arm="third", retry_multiplier=1)                # 240
    assert remaining_minor_units(ledger) == 8800
    close(ledger, entry_id="set-a", reservation_id="res-a", amount_minor_units=123)
    void(ledger, entry_id="void-b", reservation_id="res-b", now=LATER, note="test void")
    state = status(ledger)
    assert state["currency"] == "EUR"
    assert state["capMinorUnits"] == 10000
    assert state["settledMinorUnits"] == 123
    assert state["openReservationMinorUnits"] == 240
    assert state["remainingMinorUnits"] == 9637
    assert state["capExceeded"] is False
    assert state["settlementsAboveTheirReservation"] == {}
    assert state["openReservations"] == ["res-c"]
    assert state["voidedReservations"] == ["res-b"]
    assert state["conversionAllowancePercent"] == 10
    assert len(state["verifiedPrices"]) == 1
    assert "test-model" in state["verifiedPrices"][0] and "2026-10-01" in state["verifiedPrices"][0]
    assert committed_minor_units(ledger) == 363


def test_status_of_an_empty_ledger_shows_the_whole_cap():
    state = status(book(prices=[]))
    assert (state["settledMinorUnits"], state["openReservationMinorUnits"], state["remainingMinorUnits"]) == (0, 0, 10000)
    assert state["openReservations"] == [] and state["voidedReservations"] == [] and state["verifiedPrices"] == []
    assert state["capExceeded"] is False


def test_find_entry_returns_the_entry_or_nothing():
    ledger = book(entries=[reservation_row(), settlement_row()])
    assert find_entry(ledger, "set-1").kind == "SETTLEMENT"
    assert find_entry(ledger, "res-1").kind == "RESERVATION"
    assert find_entry(ledger, "res-9") is None


# --- files --------------------------------------------------------------------------------


def test_a_saved_ledger_loads_back_unchanged(tmp_path):
    ledger = book(prices=[price_row(), converted_row(model="other-model")])
    hold(ledger, entry_id="res-a", arm="baseline")
    hold(ledger, entry_id="res-b", arm="iteration")
    hold(ledger, entry_id="res-c", arm="third", model="other-model")               # 528 at the converted price
    close(ledger, entry_id="set-a", reservation_id="res-a", amount_minor_units=123)
    void(ledger, entry_id="void-b", reservation_id="res-b", now=LATER, note="test void")
    path = tmp_path / "ledger.json"
    save_ledger(ledger, path)
    again = load_ledger(path)
    assert again.model_dump(by_alias=True) == ledger.model_dump(by_alias=True)
    assert remaining_minor_units(again) == 9349
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["schema"] == "mycounsel.spend-ledger.v1"
    assert [entry["id"] for entry in written["entries"]] == ["res-a", "res-b", "res-c", "set-a", "void-b"]
    assert written["entries"][2]["conversionAllowancePercent"] == 10
    assert written["entries"][2]["price"]["listCurrency"] == "USD"


def test_save_ledger_refuses_an_unsound_history_and_leaves_the_file_alone(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = book()
    hold(ledger)
    save_ledger(ledger, path)
    before = path.read_bytes()
    ledger.entries.append(Entry.model_validate(settlement_row(reservationId="res-9")))
    with pytest.raises(ValidationError, match="does not close an earlier reservation"):
        save_ledger(ledger, path)
    assert path.read_bytes() == before


def test_load_ledger_refuses_a_file_with_an_unsound_history(tmp_path):
    path = tmp_path / "ledger.json"
    twice = [reservation_row(), settlement_row(), settlement_row(id="set-2")]
    path.write_text(json.dumps(ledger_file(entries=twice)), encoding="utf-8")
    with pytest.raises(ValidationError, match="closed twice"):
        load_ledger(path)


def test_append_adds_a_valid_entry():
    ledger = book()
    first = hold(ledger)
    closing = Entry.model_validate(settlement_row())
    candidate_budget._append(ledger, closing)
    assert ledger.entries == [first, closing]


def test_append_leaves_the_ledger_untouched_when_the_history_would_not_validate():
    ledger = book()
    first = hold(ledger)
    with pytest.raises(ValidationError, match="does not close an earlier reservation"):
        candidate_budget._append(ledger, Entry.model_validate(settlement_row(reservationId="res-9")))
    assert ledger.entries == [first]
    with pytest.raises(ValidationError, match="unique"):
        candidate_budget._append(ledger, Entry.model_validate(reservation_row(arm="iteration")))
    assert ledger.entries == [first]
    with pytest.raises(ValidationError, match="dated before"):
        candidate_budget._append(ledger, Entry.model_validate(settlement_row(recordedAt="2026-10-12T08:00:00Z")))
    assert ledger.entries == [first]
    assert remaining_minor_units(ledger) == 9520


def test_the_committed_ledger_carries_the_eur_100_cap_one_verified_price_row_and_no_entries():
    # The first real reservation ends this state; this test and the README table then change with it.
    seed = load_ledger(SEED)
    assert seed.currency == "EUR"
    assert seed.capMinorUnits == 10000
    assert seed.maxPriceAgeDays == 30
    assert seed.entries == []
    assert [row.key() for row in seed.prices] == [("gemini-3.8-flash", "gemini", "eu")]
    row = seed.prices[0]
    assert row.sourceUrl.startswith("https://")
    assert row.listCurrency == "USD" and row.conversionNote.strip() and row.allowance_percent() == 10
    state = status(seed)
    assert (state["settledMinorUnits"], state["openReservationMinorUnits"], state["remainingMinorUnits"]) == (0, 0, 10000)


def test_the_committed_price_row_gives_the_holds_the_readme_states():
    # README: 6,000 input and 12,096 output tokens hold 11 cents; twelve attempts with a retry
    # multiplier of two hold EUR 2.64. By hand at 148 and 737 minor units per million tokens:
    # 888,000 + 8,914,752 = 9.802752 minor units, x 1.10 = 10.7830272, held as 11; 11 x 12 x 2 = 264.
    # A refreshed price row changes these figures together with the README.
    before = SEED.read_bytes()
    seed = load_ledger(SEED)
    row = seed.prices[0]
    assert (row.inputMinorUnitsPerMillionTokens, row.outputMinorUnitsPerMillionTokens) == (148, 737)
    assert attempt_hold_minor_units(row, 6000, 12096, row.allowance_percent()) == 11
    verified = date.fromisoformat(row.verifiedOn)
    entry = reserve(seed, entry_id="test-res-1", experiment_id="test-exp", arm="baseline", attempts=12,
                    model="gemini-3.8-flash", provider="gemini", region="eu", max_input_tokens=6000,
                    max_output_tokens=12096, retry_multiplier=2, preregistration_sha256=PREREGISTRATION,
                    now=datetime(verified.year, verified.month, verified.day, 12, 0, 0, tzinfo=timezone.utc))
    assert (entry.perAttemptMinorUnits, entry.amountMinorUnits) == (11, 264)
    assert remaining_minor_units(seed) == 9736
    assert SEED.read_bytes() == before


# --- command line -------------------------------------------------------------------------

PRICE_COMMAND = ["price", "--model", "test-model", "--provider", "test-provider", "--region", "eu",
                 "--list-currency", "EUR", "--input-minor-units-per-million", "300",
                 "--output-minor-units-per-million", "1500", "--verified-on", "2026-10-11",
                 "--source-url", "https://example.invalid/test-prices"]


def write_ledger(directory: Path, ledger: Ledger | None = None, **overrides) -> Path:
    """A ledger file in a compact spelling, so that any rewrite by the command line shows in the bytes."""
    path = directory / "ledger.json"
    content = ledger.model_dump(by_alias=True, exclude_none=True) if ledger is not None else ledger_file(**overrides)
    path.write_text(json.dumps(content, separators=(",", ":")), encoding="utf-8")
    return path


def replaced(command: list[str], flag: str, value: str) -> list[str]:
    changed = list(command)
    changed[changed.index(flag) + 1] = value
    return changed


def test_cli_status_prints_the_totals_as_json_and_writes_nothing(tmp_path, capsys):
    ledger = book()
    hold(ledger)
    path = write_ledger(tmp_path, ledger)
    before = path.read_bytes()
    main(["--ledger", str(path), "status"])
    state = json.loads(capsys.readouterr().out)
    assert state["capMinorUnits"] == 10000
    assert state["openReservationMinorUnits"] == 480
    assert state["settledMinorUnits"] == 0
    assert state["remainingMinorUnits"] == 9520
    assert state["openReservations"] == ["res-1"]
    assert path.read_bytes() == before
    assert sorted(item.name for item in tmp_path.iterdir()) == ["ledger.json"]


def test_cli_reads_the_committed_ledger_path_when_none_is_given(tmp_path, capsys, monkeypatch):
    # `make candidate-budget-status` runs the command from the repository root without --ledger.
    folder = tmp_path / "candidates" / "mycounsel"
    folder.mkdir(parents=True)
    write_ledger(folder, capMinorUnits=4321).rename(folder / "spend-ledger.json")
    monkeypatch.chdir(tmp_path)
    main(["status"])
    assert json.loads(capsys.readouterr().out)["remainingMinorUnits"] == 4321


def test_cli_price_adds_a_row_read_from_the_provider_page(tmp_path, capsys):
    path = write_ledger(tmp_path, prices=[])
    main(["--ledger", str(path), *PRICE_COMMAND])
    assert "test-model" in capsys.readouterr().out
    ledger = load_ledger(path)
    assert [row.model_dump() for row in ledger.prices] == [price_row(verifiedOn="2026-10-11")]
    assert hold(ledger).amountMinorUnits == 480


def test_cli_price_refreshes_the_row_instead_of_adding_a_second_one(tmp_path, capsys):
    path = write_ledger(tmp_path)
    main(["--ledger", str(path), *replaced(PRICE_COMMAND, "--output-minor-units-per-million", "1600")])
    capsys.readouterr()
    assert [(row.outputMinorUnitsPerMillionTokens, row.verifiedOn) for row in load_ledger(path).prices] == [
        (1600, "2026-10-11")]


def test_cli_price_records_a_converted_price_with_its_note(tmp_path, capsys):
    path = write_ledger(tmp_path, prices=[])
    main(["--ledger", str(path), *replaced(PRICE_COMMAND, "--list-currency", "USD"), "--conversion-note", TEST_NOTE])
    capsys.readouterr()
    row = load_ledger(path).prices[0]
    assert (row.listCurrency, row.conversionNote, row.allowance_percent()) == ("USD", TEST_NOTE, 10)


@pytest.mark.parametrize("note", [[], ["--conversion-note", ""], ["--conversion-note", "   "]])
def test_cli_price_refuses_a_converted_price_without_a_note(tmp_path, note):
    path = write_ledger(tmp_path, prices=[])
    before = path.read_bytes()
    with pytest.raises(ValueError, match="converted into EUR"):
        main(["--ledger", str(path), *replaced(PRICE_COMMAND, "--list-currency", "USD"), *note])
    assert path.read_bytes() == before


def test_cli_price_cannot_drop_the_list_currency_by_omission(tmp_path, capsys):
    path = write_ledger(tmp_path, prices=[])
    before = path.read_bytes()
    command = list(PRICE_COMMAND)
    position = command.index("--list-currency")
    del command[position:position + 2]
    with pytest.raises(SystemExit) as stopped:
        main(["--ledger", str(path), *command])
    assert stopped.value.code == 2
    assert "--list-currency" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_cli_price_refuses_other_figures_while_a_reservation_is_open(tmp_path):
    ledger = book()
    hold(ledger)
    path = write_ledger(tmp_path, ledger)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="open at the old price"):
        main(["--ledger", str(path), *replaced(PRICE_COMMAND, "--output-minor-units-per-million", "9000")])
    assert path.read_bytes() == before


@pytest.mark.parametrize("command", ["reserve", "settle", "void"])
def test_cli_has_no_command_that_moves_money(tmp_path, capsys, command):
    ledger = book()
    hold(ledger)
    path = write_ledger(tmp_path, ledger)
    before = path.read_bytes()
    with pytest.raises(SystemExit) as stopped:
        main(["--ledger", str(path), command])
    assert stopped.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert path.read_bytes() == before
