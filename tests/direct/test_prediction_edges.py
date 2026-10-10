"""Edge cases for the deterministic rules and the mocked nondet paths.

Covers input bounds, deadline inclusivity, strict above/below (equality is NO),
cent rounding, error and UNRESOLVED reverts, and validator disagreement.
"""

import json

from tests.direct.conftest import (
    CG_API,
    CG_PAGE,
    CONTRACT,
    PAST,
    mock_event,
    mock_price,
    mock_price_body,
    to_hex,
)

QUESTION = "Team A wins the final"


def _event(vm, deploy, sender, predicts_yes=True, url="https://example.org/news/1"):
    c = deploy(CONTRACT)
    vm.sender = sender
    c.create_event_prediction(QUESTION, url, PAST, predicts_yes)
    return c


# ── input bounds ────────────────────────────────────────────────────────────


def test_price_target_formats_and_rejections(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "100,000.50", PAST)
    c.create_price_prediction("bitcoin", "above", "$100000.5", PAST)
    c.create_price_prediction("bitcoin", "above", "0.01", PAST)
    assert c.get_prediction(0)["target_price_usd"] == "100000.50"
    assert c.get_prediction(1)["target_price_usd"] == "100000.50"
    assert c.get_prediction(2)["target_price_usd"] == "0.01"

    for bad in ("-1", "1e5", "1.2.3", "", "$", "  ", "٢"):
        with direct_vm.expect_revert("Invalid USD amount"):
            c.create_price_prediction("bitcoin", "above", bad, PAST)
    for zero in ("0", "0.00", 0):
        with direct_vm.expect_revert("Target price must be positive"):
            c.create_price_prediction("bitcoin", "above", zero, PAST)
    # Fits in a string but not in u256 storage.
    with direct_vm.expect_revert("Invalid USD amount"):
        c.create_price_prediction("bitcoin", "above", "1" + "0" * 78, PAST)
    assert c.get_stats()["total"] == 3


def test_asset_question_and_url_bounds(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    asset = "a" * 64
    c.create_price_prediction(asset, "ABOVE", "1", PAST)
    assert c.get_prediction(0)["asset_id"] == asset

    with direct_vm.expect_revert("Invalid CoinGecko asset id"):
        c.create_price_prediction("a" * 65, "above", "1", PAST)
    with direct_vm.expect_revert("Invalid CoinGecko asset id"):
        c.create_price_prediction("bit_coin", "above", "1", PAST)
    with direct_vm.expect_revert("Invalid CoinGecko asset id"):
        c.create_price_prediction("", "above", "1", PAST)

    q10 = "0123456789"
    q280 = "q" * 280
    host = "https://example.org/"
    c.create_event_prediction(f"  {q10}  ", "https://example.org/a", PAST, True)
    c.create_event_prediction(q280, host + "a" * (512 - len(host)), PAST, True)
    assert c.get_prediction(1)["question"] == q10
    assert len(c.get_prediction(2)["resolution_url"]) == 512

    with direct_vm.expect_revert("10-280"):
        c.create_event_prediction("q" * 9, "https://example.org/a", PAST, True)
    with direct_vm.expect_revert("10-280"):
        c.create_event_prediction("q" * 281, "https://example.org/a", PAST, True)
    with direct_vm.expect_revert("https://"):
        c.create_event_prediction(QUESTION, "https://", PAST, True)
    with direct_vm.expect_revert("https://"):
        c.create_event_prediction(QUESTION, "https://example.org/a b", PAST, True)
    with direct_vm.expect_revert("https://"):
        c.create_event_prediction(QUESTION, "https://example.org/" + "a" * 500, PAST, True)

    # Naive and offset datetimes are stored as UTC, truncated to seconds.
    c.create_price_prediction("bitcoin", "above", "1", "2026-06-01T05:30:00+05:30")
    c.create_price_prediction("bitcoin", "above", "1", "2026-06-01T12:00:00")
    assert c.get_prediction(3)["resolve_after"] == "2026-06-01T00:00:00Z"
    assert c.get_prediction(4)["resolve_after"] == "2026-06-01T12:00:00Z"


def test_owner_is_deployer(direct_deploy, direct_owner):
    c = direct_deploy(CONTRACT)
    assert c.get_stats()["owner"] == to_hex(direct_owner)


# ── deadlines and status ────────────────────────────────────────────────────


def test_deadline_is_inclusive(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp("2026-06-01T00:00:00Z")
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1", "2026-06-01T00:00:00Z")
    mock_price(direct_vm, 2)
    assert c.resolve(0) == "YES"
    assert c.get_prediction(0)["resolved_at"] == "2026-06-01T00:00:00Z"


def test_one_second_before_deadline_reverts(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp("2026-05-31T23:59:59Z")
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1", "2026-06-01T00:00:00Z")
    with direct_vm.expect_revert("Too early to resolve"):
        c.resolve(0)
    assert c.get_prediction(0)["status"] == "open"
    assert c.get_stats()["open"] == 1


def test_views_for_empty_and_paging(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    assert c.get_user_stats(to_hex(direct_alice)) == {
        "points": 0,
        "correct": 0,
        "wrong": 0,
        "created": 0,
    }
    assert c.get_user_predictions(to_hex(direct_alice)) == []
    assert c.get_leaderboard(10) == []
    assert c.get_leaderboard(0) == []
    assert c.get_predictions(0, 0) == []
    assert c.get_predictions(-5, -1) == []

    for _ in range(51):
        c.create_price_prediction("bitcoin", "above", "1", PAST)
    assert len(c.get_predictions(0, 100)) == 50
    assert [p["id"] for p in c.get_predictions(50, 10)] == [50]
    assert c.get_predictions(100, 10) == []
    # Negative offset is clamped to the start of the list.
    assert c.get_predictions(-1, 1)[0]["id"] == 0


def test_leaderboard_tie_breaks_on_address(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    c = direct_deploy(CONTRACT)
    mock_price(direct_vm, 10)
    for sender in (direct_alice, direct_bob):
        direct_vm.sender = sender
        pid = c.create_price_prediction("bitcoin", "above", "1", PAST)
        c.resolve(pid)
    board = c.get_leaderboard(10)
    assert [row["points"] for row in board] == [1, 1]
    assert board == sorted(board, key=lambda row: row["user"])


# ── price outcome and rounding ──────────────────────────────────────────────


def test_price_equality_is_no_for_both_comparators(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "50", PAST)
    c.create_price_prediction("bitcoin", "below", "50", PAST)
    mock_price(direct_vm, 50)
    assert c.resolve(0) == "NO"
    assert c.resolve(1) == "NO"
    stats = c.get_user_stats(to_hex(direct_alice))
    assert stats == {"points": 0, "correct": 0, "wrong": 2, "created": 2}
    assert c.get_leaderboard(5) == []


def test_price_one_cent_boundaries(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "50", PAST)
    c.create_price_prediction("bitcoin", "below", "50", PAST)
    c.create_price_prediction("bitcoin", "above", "50", PAST)
    c.create_price_prediction("bitcoin", "below", "50", PAST)

    mock_price_body(direct_vm, '{"bitcoin":{"usd":50.01}}')
    assert c.resolve(0) == "YES"
    assert c.resolve(1) == "NO"
    assert c.get_prediction(0)["observed"] == "price_usd=50.01"

    direct_vm.clear_mocks()
    mock_price_body(direct_vm, '{"bitcoin":{"usd":49.99}}')
    assert c.resolve(2) == "NO"
    assert c.resolve(3) == "YES"
    assert c.get_user_stats(to_hex(direct_alice))["correct"] == 2


def test_float_sensitive_prices_round_half_up(direct_vm, direct_deploy, direct_alice):
    """1.005 and 8.995 are mis-rounded by int(round(float(x) * 100))."""
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1.00", PAST)
    c.create_price_prediction("bitcoin", "above", "8.99", PAST)
    c.create_price_prediction("bitcoin", "above", "0.14", PAST)
    c.create_price_prediction("bitcoin", "above", "10.02", PAST)

    mock_price_body(direct_vm, '{"bitcoin":{"usd":1.005}}')
    assert c.resolve(0) == "YES"
    assert c.get_prediction(0)["observed"] == "price_usd=1.01"

    direct_vm.clear_mocks()
    mock_price_body(direct_vm, '{"bitcoin":{"usd":8.995}}')
    assert c.resolve(1) == "YES"
    assert c.get_prediction(1)["observed"] == "price_usd=9.00"

    direct_vm.clear_mocks()
    mock_price_body(direct_vm, '{"bitcoin":{"usd":0.145}}')
    assert c.resolve(2) == "YES"
    assert c.get_prediction(2)["observed"] == "price_usd=0.15"

    direct_vm.clear_mocks()
    mock_price_body(direct_vm, '{"bitcoin":{"usd":10.025}}')
    assert c.resolve(3) == "YES"
    assert c.get_prediction(3)["observed"] == "price_usd=10.03"


def test_quoted_and_scientific_api_prices(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1", PAST)
    c.create_price_prediction("bitcoin", "above", "1", PAST)

    mock_price_body(direct_vm, '{"bitcoin":{"usd":"62345.67"}}')
    assert c.resolve(0) == "YES"
    assert c.get_prediction(0)["observed"] == "price_usd=62345.67"

    direct_vm.clear_mocks()
    mock_price_body(direct_vm, '{"bitcoin":{"usd":1.5e4}}')
    assert c.resolve(1) == "YES"
    assert c.get_prediction(1)["observed"] == "price_usd=15000.00"


def test_api_failure_falls_back_and_total_failure_stays_open(
    direct_vm, direct_deploy, direct_alice
):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1", PAST)
    c.create_price_prediction("bitcoin", "above", "1", PAST)

    direct_vm.mock_web(CG_API, {"status": 200, "body": "not-json"})
    direct_vm.mock_web(CG_PAGE, {"status": 200, "body": "Bitcoin $42"})
    direct_vm.mock_llm(r".*price oracle.*", json.dumps({"price_usd": "$42.00"}))
    assert c.resolve(0) == "YES"
    assert c.get_prediction(0)["observed"] == "price_usd=42.00"

    direct_vm.clear_mocks()
    direct_vm.mock_web(CG_API, {"status": 500, "body": ""})
    direct_vm.mock_web(CG_PAGE, {"status": 200, "body": "no price here"})
    direct_vm.mock_llm(r".*price oracle.*", json.dumps({"price_usd": "0"}))
    with direct_vm.expect_revert("Price not available"):
        c.resolve(1)
    assert c.get_prediction(1)["status"] == "open"
    assert c.get_stats()["open"] == 1 and c.get_stats()["resolved"] == 1


def test_garbled_price_llm_stays_open(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1", PAST)
    direct_vm.mock_web(CG_API, {"status": 429, "body": ""})
    direct_vm.mock_web(CG_PAGE, {"status": 200, "body": "page"})
    direct_vm.mock_llm(r".*price oracle.*", "not json at all")
    with direct_vm.expect_revert("Price not available"):
        c.resolve(0)
    assert c.get_prediction(0)["status"] == "open"


def test_price_validator_bounds_and_malformed_leader(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "100.50", PAST)
    # $100.00 is not above $100.50.
    mock_price_body(direct_vm, '{"bitcoin":{"usd":100.00}}')
    assert c.resolve(0) == "NO"

    # $101.00 is within 1.5% of $100.00, so the validator agrees even though
    # its own price would be above the strike. This is the current rule.
    direct_vm.clear_mocks()
    mock_price_body(direct_vm, '{"bitcoin":{"usd":101.00}}')
    assert direct_vm.run_validator() is True

    direct_vm.clear_mocks()
    mock_price_body(direct_vm, '{"bitcoin":{"usd":100.00}}')
    assert direct_vm.run_validator(leader_result={"price_cents": 0, "outcome": "NO"}) is False
    assert direct_vm.run_validator(leader_result={"outcome": "YES"}) is False
    assert direct_vm.run_validator(leader_result="nope") is False
    assert direct_vm.run_validator(leader_result={"price_cents": True, "outcome": "NO"}) is False
    # Consistent leader payload, same price the validator observes.
    assert (
        direct_vm.run_validator(leader_result={"price_cents": 10000, "outcome": "NO"})
        is True
    )


def test_tolerance_boundary(direct_vm, direct_deploy, direct_alice):
    """1.5% of the larger price is accepted; one cent past that is not.

    Leader observation is $10000.00 (1_000_000 cents). The largest validator
    price that still satisfies abs(a-b)*10000 <= max(a,b)*150 is $10152.28.
    """
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1", PAST)
    mock_price_body(direct_vm, '{"bitcoin":{"usd":10000.00}}')
    assert c.resolve(0) == "YES"

    direct_vm.clear_mocks()
    mock_price_body(direct_vm, '{"bitcoin":{"usd":10152.28}}')
    assert direct_vm.run_validator() is True

    direct_vm.clear_mocks()
    mock_price_body(direct_vm, '{"bitcoin":{"usd":10152.29}}')
    assert direct_vm.run_validator() is False


# ── event errors ────────────────────────────────────────────────────────────


def test_event_creator_loses_when_predicting_yes(direct_vm, direct_deploy, direct_alice):
    c = _event(direct_vm, direct_deploy, direct_alice, predicts_yes=True)
    mock_event(direct_vm, "NO", "the source says no")
    assert c.resolve(0) == "NO"
    stats = c.get_user_stats(to_hex(direct_alice))
    assert stats["points"] == 0 and stats["wrong"] == 1 and stats["correct"] == 0


def test_event_evidence_is_truncated(direct_vm, direct_deploy, direct_alice):
    c = _event(direct_vm, direct_deploy, direct_alice)
    mock_event(direct_vm, "YES", "e" * 400)
    assert c.resolve(0) == "YES"
    assert c.get_prediction(0)["observed"] == "e" * 280


def test_event_markdown_fenced_json(direct_vm, direct_deploy, direct_alice):
    c = _event(direct_vm, direct_deploy, direct_alice)
    direct_vm.mock_web(r".*example\.org/news.*", {"status": 200, "body": "article"})
    direct_vm.mock_llm(
        r".*impartial prediction-market resolver.*",
        '```json\n{"outcome": "YES", "evidence": "fenced"}\n```',
    )
    assert c.resolve(0) == "YES"
    assert c.get_prediction(0)["observed"] == "fenced"


def test_event_invalid_json_is_unresolved(direct_vm, direct_deploy, direct_alice):
    c = _event(direct_vm, direct_deploy, direct_alice)
    direct_vm.mock_web(r".*example\.org/news.*", {"status": 200, "body": "article"})
    direct_vm.mock_llm(r".*impartial prediction-market resolver.*", "sure, whatever")
    with direct_vm.expect_revert("Outcome cannot be determined yet"):
        c.resolve(0)
    assert c.get_prediction(0)["status"] == "open"
    assert c.get_stats()["resolved"] == 0


def test_event_validator_rejects_malformed_leader(direct_vm, direct_deploy, direct_alice):
    c = _event(direct_vm, direct_deploy, direct_alice)
    mock_event(direct_vm, "YES", "leader wording")
    c.resolve(0)

    direct_vm.clear_mocks()
    mock_event(direct_vm, "YES", "same verdict")
    assert direct_vm.run_validator(leader_result={"evidence": "no outcome"}) is False
    assert direct_vm.run_validator(leader_result=["YES"]) is False
    assert direct_vm.run_validator(leader_result={"outcome": "MAYBE"}) is False
    assert (
        direct_vm.run_validator(leader_result={"outcome": "YES", "evidence": "other"})
        is True
    )


def test_invalid_user_address_reverts(direct_vm, direct_deploy):
    c = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("invalid address"):
        c.get_user_stats("not-an-address")
    with direct_vm.expect_revert("Prediction not found"):
        c.resolve(-1)
