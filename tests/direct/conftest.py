"""Shared helpers for direct-mode tests.

Fixtures (``direct_vm``, ``direct_deploy``, ``direct_alice``, ``direct_bob``,
``direct_charlie``, ``direct_owner``) come from the ``genlayer-test`` pytest
plugin. They run the contract in-process and mock ``gl.nondet`` web/LLM calls,
so this suite does not need a GenLayer node.
"""

import json

CONTRACT = "contracts/prediction_resolver.py"

PAST = "2026-01-01T00:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"
CG_API = r".*api\.coingecko\.com/api/v3/simple/price.*"
CG_PAGE = r".*coingecko\.com/en/coins/.*"
NEWS = r".*example\.org/news.*"


def to_hex(addr):
    if hasattr(addr, "as_hex"):
        return addr.as_hex
    from genlayer.py.types import Address

    return Address(addr).as_hex


def mock_price(vm, usd, asset="bitcoin"):
    vm.mock_web(
        CG_API,
        {"status": 200, "body": json.dumps({asset: {"usd": usd}})},
    )


def mock_price_body(vm, body):
    vm.mock_web(CG_API, {"status": 200, "body": body})


def mock_event(vm, outcome, evidence="source says so"):
    vm.mock_web(NEWS, {"status": 200, "body": "Some article text"})
    vm.mock_llm(
        r".*impartial prediction-market resolver.*",
        json.dumps({"outcome": outcome, "evidence": evidence}),
    )
