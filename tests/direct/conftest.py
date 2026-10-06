"""Shared helpers for direct-mode tests."""

CONTRACT = "contracts/prediction_resolver.py"


def to_hex(addr):
    if hasattr(addr, "as_hex"):
        return addr.as_hex
    from genlayer.py.types import Address

    return Address(addr).as_hex
