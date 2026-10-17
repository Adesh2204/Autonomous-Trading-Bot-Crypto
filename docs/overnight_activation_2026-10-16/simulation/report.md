# Anchorium SIMULATION

{
  "mode": "SIMULATION",
  "status": "SIMULATION_COMPLETE",
  "source_hash": "f3575dc88c09696af5a3b765f43c71f91eba082a568deb4f40d90aaf92602e18",
  "synthetic_only": true,
  "exchange_writes": 0,
  "actual_realized_pnl": null,
  "episodes": [
    {
      "scenario": "win_then_loss",
      "state": "FLAT_VERIFIED",
      "cycles": 2,
      "simulated_net": "1.300000",
      "positions": [],
      "open_orders": [],
      "simulated_fills": [
        {
          "symbol": "par:BTC",
          "timestamp_ms": 1790942400014,
          "trade_id": "101",
          "order_id": "101",
          "side": "BUY",
          "quantity": "1.0000",
          "price": "100.15",
          "fee": "0.1",
          "fee_token": "USDPR",
          "closed_pnl": "0",
          "start_position": "0",
          "source": "EXCHANGE_REPORTED_FILL",
          "exchange_ts": "2026-10-02T12:00:00.014+00:00",
          "received_ts": "2026-10-02T12:01:00.021+00:00",
          "processed_ts": "2026-10-02T12:01:00.021+00:00"
        },
        {
          "symbol": "par:BTC",
          "timestamp_ms": 1790942400031,
          "trade_id": "103",
          "order_id": "103",
          "side": "SELL",
          "quantity": "1.0000",
          "price": "105",
          "fee": "0.1",
          "fee_token": "USDPR",
          "closed_pnl": "4.850000",
          "start_position": "0",
          "source": "EXCHANGE_REPORTED_FILL",
          "exchange_ts": "2026-10-02T12:00:00.031+00:00",
          "received_ts": "2026-10-02T12:01:00.037+00:00",
          "processed_ts": "2026-10-02T12:01:00.037+00:00"
        },
        {
          "symbol": "par:BTC",
          "timestamp_ms": 1790942460013,
          "trade_id": "104",
          "order_id": "104",
          "side": "BUY",
          "quantity": "1.0000",
          "price": "100.15",
          "fee": "0.1",
          "fee_token": "USDPR",
          "closed_pnl": "0",
          "start_position": "0",
          "source": "EXCHANGE_REPORTED_FILL",
          "exchange_ts": "2026-10-02T12:01:00.013+00:00",
          "received_ts": "2026-10-02T12:01:00.037+00:00",
          "processed_ts": "2026-10-02T12:01:00.037+00:00"
        },
        {
          "symbol": "par:BTC",
          "timestamp_ms": 1790942460030,
          "trade_id": "106",
          "order_id": "106",
          "side": "SELL",
          "quantity": "1.0000",
          "price": "97",
          "fee": "0.1",
          "fee_token": "USDPR",
          "closed_pnl": "-3.150000",
          "start_position": "0",
          "source": "EXCHANGE_REPORTED_FILL",
          "exchange_ts": "2026-10-02T12:01:00.030+00:00",
          "received_ts": "2026-10-02T12:01:00.037+00:00",
          "processed_ts": "2026-10-02T12:01:00.037+00:00"
        }
      ],
      "synthetic_signed_actions": 8,
      "integrity": "ok"
    },
    {
      "scenario": "rejected_entry",
      "state": "REJECTED",
      "cycles": 0,
      "simulated_net": "0",
      "positions": [],
      "open_orders": [],
      "simulated_fills": [],
      "synthetic_signed_actions": 1,
      "integrity": "ok"
    },
    {
      "scenario": "uncertain_entry",
      "state": "UNKNOWN",
      "cycles": 0,
      "simulated_net": "0",
      "positions": [],
      "open_orders": [],
      "simulated_fills": [],
      "synthetic_signed_actions": 1,
      "integrity": "ok"
    },
    {
      "scenario": "partial_entry",
      "state": "RECOVERY_REQUIRED",
      "cycles": 0,
      "simulated_net": "0",
      "positions": [
        {
          "symbol": "par:BTC",
          "quantity": "0.5000",
          "entry_price": "100.15",
          "unrealized_pnl": "0",
          "margin_used": "10",
          "liquidation_price": null,
          "leverage": null
        }
      ],
      "open_orders": [],
      "simulated_fills": [
        {
          "symbol": "par:BTC",
          "timestamp_ms": 1790942400014,
          "trade_id": "101",
          "order_id": "101",
          "side": "BUY",
          "quantity": "0.5000",
          "price": "100.15",
          "fee": "0.1",
          "fee_token": "USDPR",
          "closed_pnl": "0",
          "start_position": "0",
          "source": "EXCHANGE_REPORTED_FILL",
          "exchange_ts": "2026-10-02T12:00:00.014+00:00",
          "received_ts": "2026-10-02T12:00:00.015+00:00",
          "processed_ts": "2026-10-02T12:00:00.015+00:00"
        }
      ],
      "synthetic_signed_actions": 1,
      "integrity": "ok"
    },
    {
      "scenario": "partial_exit",
      "state": "RECOVERY_REQUIRED",
      "cycles": 0,
      "simulated_net": "0",
      "positions": [
        {
          "symbol": "par:BTC",
          "quantity": "0.5000",
          "entry_price": "100.15",
          "unrealized_pnl": "0",
          "margin_used": "10",
          "liquidation_price": null,
          "leverage": null
        }
      ],
      "open_orders": [
        {
          "coin": "par:BTC",
          "side": "A",
          "sz": "1",
          "limitPx": "96.254",
          "oid": 102,
          "cloid": "0x1f67427ee6da0fac7226fad280db235c",
          "isTrigger": true,
          "reduceOnly": true,
          "triggerPx": "96.737",
          "orderType": "Stop Limit",
          "timestamp": 1790942400000
        }
      ],
      "simulated_fills": [
        {
          "symbol": "par:BTC",
          "timestamp_ms": 1790942400014,
          "trade_id": "101",
          "order_id": "101",
          "side": "BUY",
          "quantity": "1.0000",
          "price": "100.15",
          "fee": "0.1",
          "fee_token": "USDPR",
          "closed_pnl": "0",
          "start_position": "0",
          "source": "EXCHANGE_REPORTED_FILL",
          "exchange_ts": "2026-10-02T12:00:00.014+00:00",
          "received_ts": "2026-10-02T12:00:00.032+00:00",
          "processed_ts": "2026-10-02T12:00:00.032+00:00"
        },
        {
          "symbol": "par:BTC",
          "timestamp_ms": 1790942400031,
          "trade_id": "103",
          "order_id": "103",
          "side": "SELL",
          "quantity": "0.5000",
          "price": "105",
          "fee": "0.1",
          "fee_token": "USDPR",
          "closed_pnl": "2.425000",
          "start_position": "0",
          "source": "EXCHANGE_REPORTED_FILL",
          "exchange_ts": "2026-10-02T12:00:00.031+00:00",
          "received_ts": "2026-10-02T12:00:00.032+00:00",
          "processed_ts": "2026-10-02T12:00:00.032+00:00"
        }
      ],
      "synthetic_signed_actions": 3,
      "integrity": "ok"
    }
  ],
  "native_qualification": false,
  "note": "Synthetic whole-unit venue makes one lot minimum-compliant. Actual par metadata is never changed; fixtures cannot qualify a real stop or account."
}
