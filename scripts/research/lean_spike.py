"""Offline LEAN adapter probe. Uses bundled sample data, never broker credentials.

Run with: .venv/bin/python scripts/research/lean_spike.py --output /tmp/tm-lean-spike
The pinned image must already be installed. Results are engineering evidence,
not an investment backtest. Docker network access is disabled for every run.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess


IMAGE = "quantconnect/lean@sha256:8ba05f8a5425efb3b2d32299803a5d3bd5da953caf4597804b6763c8d9fa8736"

ALGORITHM = '''from AlgorithmImports import *
import json

class TradeMasterLeanSpike(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2014, 6, 5)
        self.set_end_date(2014, 6, 12)
        self.set_cash(10000)
        self.asset = self.add_equity("AAPL", Resolution.DAILY)
        self.asset.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.asset.set_fee_model(ConstantFeeModel(1))
        self.asset.set_slippage_model(ConstantSlippageModel(0.001))
        self.set_benchmark(self.asset.symbol)
        self.sent = False
        self.records = []

    def on_data(self, data):
        if not self.sent and data.bars.contains_key(self.asset.symbol):
            self.sent = True
            self.records.append({"kind": "target", "utc": self.utc_time.isoformat(), "quantity": 5})
            self.market_on_open_order(self.asset.symbol, 5)
        for symbol, split in data.splits.items():
            self.records.append({"kind": "split", "utc": self.utc_time.isoformat(), "factor": float(split.split_factor), "type": str(split.type), "price": float(self.asset.price), "cash": float(self.portfolio.cash), "quantity": float(self.portfolio[self.asset.symbol].quantity)})

    def on_order_event(self, event):
        if event.status == OrderStatus.FILLED:
            self.records.append({"kind": "fill", "utc": event.utc_time.isoformat(), "quantity": float(event.fill_quantity), "price": float(event.fill_price), "fee": float(event.order_fee.value.amount)})

    def on_end_of_algorithm(self):
        self.records.append({"kind": "account", "cash": float(self.portfolio.cash), "quantity": float(self.portfolio[self.asset.symbol].quantity), "equity": float(self.portfolio.total_portfolio_value)})
        with open("/Results/adapter-probe.json", "w") as stream:
            json.dump(self.records, stream, sort_keys=True)
'''


def configuration():
    return {
        "environment": "backtesting", "live-mode": False,
        "algorithm-type-name": "TradeMasterLeanSpike", "algorithm-language": "Python",
        "algorithm-location": "/Probe/main.py", "data-folder": "/Lean/Data",
        "results-destination-folder": "/Results", "object-store-root": "/Results/storage",
        "log-handler": "QuantConnect.Logging.CompositeLogHandler",
        "messaging-handler": "QuantConnect.Messaging.Messaging",
        "job-queue-handler": "QuantConnect.Queues.JobQueue",
        "api-handler": "QuantConnect.Api.Api",
        "map-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider",
        "factor-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider",
        "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",
        "data-channel-provider": "DataChannelProvider",
        "object-store": "QuantConnect.Lean.Engine.Storage.LocalObjectStore",
        "data-aggregator": "QuantConnect.Lean.Engine.DataFeeds.AggregationManager",
        "job-user-id": "0", "job-project-id": "0", "job-organization-id": "",
        "maximum-data-points-per-chart-series": 10000,
        "environments": {"backtesting": {
            "live-mode": False,
            "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
            "result-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
            "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
            "real-time-handler": "QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler",
            "history-provider": ["QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider"],
            "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler",
        }},
    }


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    probe = output / "probe"
    probe.mkdir(exist_ok=True)
    (probe / "main.py").write_text(ALGORITHM)
    (probe / "config.json").write_text(json.dumps(configuration()))
    records = []
    for number in (1, 2):
        destination = output / f"run-{number}"
        destination.mkdir(exist_ok=True)
        with (destination / "launcher.log").open("w") as log:
            completed = subprocess.run([
                "docker", "run", "--rm", "--network", "none", "--cpus", "2", "--memory", "3g",
                "-v", f"{probe.resolve()}:/Probe:ro", "-v", f"{destination.resolve()}:/Results",
                IMAGE, "--config", "/Probe/config.json",
            ], stdout=log, stderr=subprocess.STDOUT, timeout=120, check=False)
        artifact = destination / "adapter-probe.json"
        if completed.returncode or not artifact.exists():
            raise RuntimeError(f"LEAN probe failed; inspect {destination / 'launcher.log'}")
        records.append(json.loads(artifact.read_text()))
    assert records[0] == records[1], "two fresh engine runs did not reproduce"
    target = next(row for row in records[0] if row["kind"] == "target")
    fill = next(row for row in records[0] if row["kind"] == "fill")
    account = records[0][-1]
    assert fill["utc"] > target["utc"], "close-derived target filled without waiting for next session"
    assert fill["fee"] == 1 and fill["quantity"] == 5
    split = next(row for row in records[0] if row["kind"] == "split" and row["type"] == "SPLIT_OCCURRED")
    exact_quantity = fill["quantity"] / split["factor"]
    expected_quantity = math.floor(exact_quantity)
    expected_cash = 10000 - fill["quantity"] * fill["price"] - fill["fee"] + (exact_quantity - expected_quantity) * split["price"]
    assert account["quantity"] == expected_quantity, "split quantity did not follow the recorded factor"
    assert abs(account["cash"] - expected_cash) < 0.01, "fractional-share cash compensation did not reconcile"
    report = {"image": IMAGE, "reproducible": True, "next_session_fill": True, "explicit_fee": True, "split_accounting": True, "records": records[0], "limitations": ["Bundled AAPL sample; no strategy profitability inference", "Rounded split factor yields 34 shares plus fractional-share cash compensation, not 35 shares", "Daily market-on-open fills are timestamped when the daily bar arrives; execution-price time must be tracked separately", "Shared production strategy parity and full adapter integration still required"]}
    (output / "probe-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
