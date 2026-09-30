"""Phase 6 increment 1 tests: the engine core, hand-computed.

The golden scenario's every number is worked out in the test itself
(Decimal arithmetic, no run of the system involved in deriving the
expectations): fills at the next bar's open through explicit slippage,
commission on absolute notional, average-cost realisation, and the
closing identity ``equity == capital + realised - fees + unrealised``.

Also covered here, because they are the exit criteria that live in the
loop itself: the bounded history (no future access), the final-bar
expiry, risk evaluation invoked for every order and able to refuse,
strict determinism, and the causality assertion as a second layer
behind the data validation.
"""
