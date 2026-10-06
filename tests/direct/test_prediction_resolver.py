"""Direct-mode tests for PredictionResolver (web + LLM are mocked)."""

import json

from tests.direct.conftest import CONTRACT, to_hex

PAST = "2026-01-01T00:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"
CG_API = r".*api\.coingecko\.com/api/v3/simple/price.*"
CG_PAGE = r".*coingecko\.com/en/coins/.*"
NEWS = r".*example\.org/news.*"


def _mock_price(vm, usd):
    vm.mock_web(CG_API, {"status": 200, "body": json.dumps({"bitcoin": {"usd": usd}})})


def _mock_event(vm, outcome, evidence="source says so"):
    vm.mock_web(NEWS, {"status": 200, "body": "Some article text"})
    vm.mock_llm(
        r".*impartial prediction-market resolver.*",
        json.dumps({"outcome": outcome, "evidence": evidence}),
    )


# ── creation ────────────────────────────────────────────────────────────────


def test_create_price_prediction(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    pid = c.create_price_prediction("Bitcoin", "above", "100000.5", PAST)
    assert pid == 0
    p = c.get_prediction(0)
    assert p["kind"] == "price"
    assert p["asset_id"] == "bitcoin"
    assert p["target_price_usd"] == "100000.50"
    assert p["status"] == "open"
    assert p["creator"] == to_hex(direct_alice)
    assert p["resolve_after"] == "2026-01-01T00:00:00Z"
    assert c.get_stats()["open"] == 1
    assert c.get_user_predictions(to_hex(direct_alice)) == [0]


def test_numeric_target_price_accepted(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("ethereum", "below", 2500, PAST)
    assert c.get_prediction(0)["target_price_usd"] == "2500.00"
    with direct_vm.expect_revert("Invalid USD amount"):
        c.create_price_prediction("ethereum", "below", True, PAST)


def test_create_event_prediction(direct_vm, direct_deploy, direct_bob):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_bob
    c.create_event_prediction(
        "Team A wins the 2026 final", "https://example.org/news/final", PAST, False
    )
    p = c.get_prediction(0)
    assert p["kind"] == "event"
    assert p["creator_predicts_yes"] is False
    assert p["target_price_usd"] == ""


def test_create_validation_errors(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Comparator must be"):
        c.create_price_prediction("bitcoin", "equal", "1", PAST)
    with direct_vm.expect_revert("Invalid USD amount"):
        c.create_price_prediction("bitcoin", "above", "abc", PAST)
    with direct_vm.expect_revert("At most 2 decimals"):
        c.create_price_prediction("bitcoin", "above", "1.234", PAST)
    with direct_vm.expect_revert("Invalid CoinGecko asset id"):
        c.create_price_prediction("bit coin!", "above", "1", PAST)
    with direct_vm.expect_revert("Invalid datetime"):
        c.create_price_prediction("bitcoin", "above", "1", "tomorrow")
    with direct_vm.expect_revert("https://"):
        c.create_event_prediction("Something will happen", "http://x.org", PAST, True)
    with direct_vm.expect_revert("10-280"):
        c.create_event_prediction("short", "https://x.org", PAST, True)
    assert c.get_stats()["total"] == 0


# ── price resolution ────────────────────────────────────────────────────────


def test_resolve_price_yes_awards_point(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "50000", PAST)
    _mock_price(direct_vm, 62345.67)

    direct_vm.sender = direct_bob  # anyone can resolve
    assert c.resolve(0) == "YES"

    p = c.get_prediction(0)
    assert p["status"] == "resolved"
    assert p["outcome"] == "YES"
    assert p["observed"] == "price_usd=62345.67"
    assert p["resolver"] == to_hex(direct_bob)
    alice = to_hex(direct_alice)
    assert c.get_user_stats(alice) == {"points": 1, "correct": 1, "wrong": 0, "created": 1}
    assert c.get_leaderboard(10) == [{"user": alice, "points": 1}]
    assert c.get_stats()["resolved"] == 1 and c.get_stats()["open"] == 0


def test_resolve_price_below_no(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "below", "50000", PAST)
    _mock_price(direct_vm, 62345.67)
    assert c.resolve(0) == "NO"
    stats = c.get_user_stats(to_hex(direct_alice))
    assert stats["points"] == 0 and stats["wrong"] == 1
    assert c.get_leaderboard(10) == []


def test_price_fallback_to_llm_page(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "50000", PAST)
    direct_vm.mock_web(CG_API, {"status": 429, "body": "rate limited"})
    direct_vm.mock_web(CG_PAGE, {"status": 200, "body": "Bitcoin price $61,000.10"})
    direct_vm.mock_llm(r".*price oracle.*", json.dumps({"price_usd": "61,000.10"}))
    assert c.resolve(0) == "YES"
    assert c.get_prediction(0)["observed"] == "price_usd=61000.10"


def test_price_validator_tolerance(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "50000", PAST)
    _mock_price(direct_vm, 60000)
    c.resolve(0)

    # validator sees a slightly different price (0.5 %) -> agrees
    direct_vm.clear_mocks()
    _mock_price(direct_vm, 60300)
    assert direct_vm.run_validator() is True

    # validator sees a very different price (10 %) -> disagrees
    direct_vm.clear_mocks()
    _mock_price(direct_vm, 66000)
    assert direct_vm.run_validator() is False

    # leader lying about the outcome -> disagrees
    direct_vm.clear_mocks()
    _mock_price(direct_vm, 60000)
    assert (
        direct_vm.run_validator(leader_result={"price_cents": 6000000, "outcome": "NO"})
        is False
    )

    # leader errored -> disagrees
    assert direct_vm.run_validator(leader_error=Exception("boom")) is False


# ── event resolution ────────────────────────────────────────────────────────


def test_resolve_event_creator_wins_on_no(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_event_prediction("Team A wins the final", "https://example.org/news/1", PAST, False)
    _mock_event(direct_vm, "NO", "Team B won 2-1")
    assert c.resolve(0) == "NO"
    p = c.get_prediction(0)
    assert p["observed"] == "Team B won 2-1"
    assert c.get_user_stats(to_hex(direct_alice))["points"] == 1


def test_resolve_event_unresolved_reverts(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_event_prediction("Team A wins the final", "https://example.org/news/1", PAST, True)
    _mock_event(direct_vm, "UNRESOLVED")
    with direct_vm.expect_revert("Outcome cannot be determined yet"):
        c.resolve(0)
    assert c.get_prediction(0)["status"] == "open"


def test_event_garbage_llm_is_unresolved(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_event_prediction("Team A wins the final", "https://example.org/news/1", PAST, True)
    _mock_event(direct_vm, "MAYBE")
    with direct_vm.expect_revert("Outcome cannot be determined yet"):
        c.resolve(0)


def test_event_validator_compares_verdict_only(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_event_prediction("Team A wins the final", "https://example.org/news/1", PAST, True)
    _mock_event(direct_vm, "YES", "leader wording")
    c.resolve(0)

    direct_vm.clear_mocks()
    _mock_event(direct_vm, "YES", "completely different wording")
    assert direct_vm.run_validator() is True

    direct_vm.clear_mocks()
    _mock_event(direct_vm, "NO", "validator disagrees")
    assert direct_vm.run_validator() is False


# ── lifecycle rules ─────────────────────────────────────────────────────────


def test_too_early_to_resolve(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1", FUTURE)
    with direct_vm.expect_revert("Too early to resolve"):
        c.resolve(0)
    assert c.get_prediction(0)["status"] == "open"


def test_resolvable_after_deadline(direct_vm, direct_deploy, direct_alice):
    # block time is captured per deployment in direct mode, so warp first
    direct_vm.warp("2099-01-02T00:00:00Z")
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1", FUTURE)
    _mock_price(direct_vm, 10)
    assert c.resolve(0) == "YES"
    p = c.get_prediction(0)
    assert p["created_at"] == "2099-01-02T00:00:00Z"
    assert p["resolved_at"] == "2099-01-02T00:00:00Z"


def test_double_resolve_and_cancel_rules(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    c.create_price_prediction("bitcoin", "above", "1", PAST)
    c.create_price_prediction("bitcoin", "above", "2", PAST)
    _mock_price(direct_vm, 10)
    c.resolve(0)
    with direct_vm.expect_revert("Prediction is not open"):
        c.resolve(0)
    with direct_vm.expect_revert("Prediction is not open"):
        c.cancel(0)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Only the creator can cancel"):
        c.cancel(1)
    direct_vm.sender = direct_alice
    c.cancel(1)
    assert c.get_prediction(1)["status"] == "cancelled"
    with direct_vm.expect_revert("Prediction is not open"):
        c.resolve(1)
    with direct_vm.expect_revert("Prediction not found"):
        c.get_prediction(7)
    assert c.get_stats() == {
        "total": 2,
        "open": 0,
        "resolved": 1,
        "cancelled": 1,
        "owner": c.get_stats()["owner"],
    }


def test_pagination_and_leaderboard_order(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    c = direct_deploy(CONTRACT)
    _mock_price(direct_vm, 100)
    for sender, n in ((direct_alice, 1), (direct_bob, 3), (direct_charlie, 2)):
        direct_vm.sender = sender
        for _ in range(n):
            pid = c.create_price_prediction("bitcoin", "above", "1", PAST)
            c.resolve(pid)
    assert len(c.get_predictions(0, 100)) == 6
    page = c.get_predictions(4, 10)
    assert [p["id"] for p in page] == [4, 5]
    board = c.get_leaderboard(2)
    assert board == [
        {"user": to_hex(direct_bob), "points": 3},
        {"user": to_hex(direct_charlie), "points": 2},
    ]
    assert c.get_user_predictions(to_hex(direct_bob)) == [1, 2, 3]
