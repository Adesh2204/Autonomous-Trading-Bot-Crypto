"""UTC event clocks. Missing exchange clocks stay null; age is not wire latency."""
from datetime import datetime, timezone
import time


def utc_ms(value):
    return None if value is None else datetime.fromtimestamp(value/1000,timezone.utc).isoformat(timespec='milliseconds')


def timing(processed_ms=None, *, exchange_ms=None, received_ms=None, source='LOCAL_PROCESS'):
    processed_ms=time.time_ns()//1_000_000 if processed_ms is None else processed_ms
    received_ms=processed_ms if received_ms is None else received_ms
    delta=None if exchange_ms is None else received_ms-exchange_ms
    return dict(exchange_ts=utc_ms(exchange_ms),received_ts=utc_ms(received_ms),
        processed_ts=utc_ms(processed_ms),timestamp_source=source,
        exchange_to_receive_ms=delta if delta is not None and delta>=0 else None,
        receive_to_process_ms=processed_ms-received_ms if processed_ms>=received_ms else None,
        clock_skew_detected=(delta is not None and delta<0) or processed_ms<received_ms)
