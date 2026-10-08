#!/usr/bin/env python3
"""Polymarket fee helpers.

Source: https://docs.polymarket.com/polymarket-learn/trading/fees

Crypto markets (as of docs):
  - taker feeRate = 0.07
  - maker feeRate = 0
  - rebateRate = 0.20 (share of taker fees rebated to makers)

Taker fee in USDC for shares C at price p:
  fee = C * feeRate * p * (1 - p)
"""
from __future__ import annotations

CRYPTO_TAKER_FEE_RATE = 0.07
CRYPTO_MAKER_FEE_RATE = 0.0
CRYPTO_REBATE_RATE = 0.20

CATEGORY_TAKER = {
    "crypto": CRYPTO_TAKER_FEE_RATE,
}


def fee_rate(volume_tier=None, category: str = "crypto") -> float:
    """Return taker feeRate. volume_tier reserved for future tiered schedules."""
    _ = volume_tier  # reserved
    return float(CATEGORY_TAKER.get((category or "crypto").lower(), CRYPTO_TAKER_FEE_RATE))


def taker_fee_usdc(shares: float, price: float, category: str = "crypto",
                   volume_tier=None) -> float:
    """USDC taker fee for buying/selling `shares` at probability price `price`."""
    c = float(shares or 0.0)
    p = float(price or 0.0)
    rate = fee_rate(volume_tier=volume_tier, category=category)
    return c * rate * p * (1.0 - p)


def maker_fee_usdc(shares: float, price: float, category: str = "crypto") -> float:
    _ = (shares, price, category)
    return 0.0
