"""Explicit research-only volatility policies. Never imported into live permissions."""
from dataclasses import asdict, dataclass
import math
import config


@dataclass(frozen=True)
class VolatilityPolicy:
    name: str = 'BASELINE_CURRENT_POLICY'
    live_atr_floor: float = config.INTRADAY_ATR_MIN_PCT
    standby_threshold: float = config.STANDBY_ATR_THRESHOLD
    recovery_threshold: float = config.STANDBY_RECOVERY_THRESHOLD
    standby_confirmations: int = config.STANDBY_CONFIRMATION_COUNT
    recovery_confirmations: int = config.STANDBY_RECOVERY_CONFIRMATION_COUNT
    firewall_low_confirmations: int = config.ATR_LOW_CONFIRMATION_COUNT
    firewall_recovery_confirmations: int = config.ATR_RECOVERY_CONFIRMATION_COUNT

    def __post_init__(self):
        thresholds=(self.live_atr_floor,self.standby_threshold,self.recovery_threshold)
        counts=(self.standby_confirmations,self.recovery_confirmations,self.firewall_low_confirmations,self.firewall_recovery_confirmations)
        if not self.name or any(not math.isfinite(v) or v<=0 or v>=1 for v in thresholds) or any(type(n) is not int or n<1 for n in counts):
            raise ValueError('INVALID_RESEARCH_POLICY')
        if self.name=='BASELINE_CURRENT_POLICY':
            expected=(config.INTRADAY_ATR_MIN_PCT,config.STANDBY_ATR_THRESHOLD,config.STANDBY_RECOVERY_THRESHOLD,
                      config.STANDBY_CONFIRMATION_COUNT,config.STANDBY_RECOVERY_CONFIRMATION_COUNT,
                      config.ATR_LOW_CONFIRMATION_COUNT,config.ATR_RECOVERY_CONFIRMATION_COUNT)
            if thresholds+counts!=expected:
                raise ValueError('EXPERIMENT_MUST_HAVE_DISTINCT_NAME')

    def report(self):
        return asdict(self)


class ResearchPolicyState:
    def __init__(self,policy):
        self.policy=policy
        self.standby=self.firewall_standby=False
        self.low=self.healthy=self.firewall_low=self.firewall_healthy=0

    def step(self,atr,price,count):
        if count<config.MIN_CANDLES_BEFORE_TRADE:
            return ['WARMUP']
        if not math.isfinite(atr) or not math.isfinite(price) or atr<=0 or price<=0:
            return ['INVALID_INDICATORS']
        p=self.policy; ratio=atr/price
        self.low=self.low+1 if ratio<p.standby_threshold else 0
        self.healthy=self.healthy+1 if ratio>=p.recovery_threshold else 0
        self.firewall_low=self.firewall_low+1 if ratio<p.live_atr_floor else 0
        self.firewall_healthy=self.firewall_healthy+1 if ratio>=p.live_atr_floor else 0
        if self.low>=p.standby_confirmations:self.standby=True
        if self.healthy>=p.recovery_confirmations:self.standby=False
        if self.firewall_low>=p.firewall_low_confirmations:self.firewall_standby=True
        if self.firewall_healthy>=p.firewall_recovery_confirmations:self.firewall_standby=False
        reasons=[]
        if ratio<p.live_atr_floor:reasons.append('ATR_BELOW_LIVE_MINIMUM')
        if self.standby:reasons.append('VOLATILITY_STANDBY')
        if self.firewall_standby:reasons.append('ATR_PERSISTENT_LOW_STANDBY')
        return reasons
