# packages/backtesting — Backtest engine (Phase 6)

Historical simulation with correct sequencing, explicit costs, and a
reproducible run manifest.

**Status: not implemented.** No simulated results exist in this repository.

Requirements the engine must satisfy:

- validated, version-pinned datasets only;
- strict time ordering with a documented intrabar rule;
- explicit commission and slippage models, recorded per run;
- exact numerics for money; drawdown and exposure reported;
- causality enforced: an order at time *t* uses information available before *t*;
- look-ahead, leakage and survivorship-bias detection;
- every run reproducible from its manifest (code version + data version +
  parameters);
- simulated orders pass through the same trade gate used in paper trading.

A backtest is evidence about the past, not a promise about the future, and
reports must say so.

See [docs/architecture/backtesting.md](../../docs/architecture/backtesting.md)
and [docs/research/backtesting-methodology.md](../../docs/research/backtesting-methodology.md).
