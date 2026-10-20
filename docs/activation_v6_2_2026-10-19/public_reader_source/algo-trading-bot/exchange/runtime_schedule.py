"""Operating cadence only. No strategy thresholds or activation permissions."""
from dataclasses import dataclass
import math
from .base_exchange import ExchangeError


@dataclass(frozen=True)
class RuntimeSchedule:
    scan_interval_seconds: float=300
    management_interval_seconds: float=1
    export_interval_seconds: float=30

    def __post_init__(self):
        for value,low,high in ((self.scan_interval_seconds,1,3600),
                               (self.management_interval_seconds,.25,30),
                               (self.export_interval_seconds,1,300)):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
                raise ExchangeError('INVALID_RUNTIME_SCHEDULE')
