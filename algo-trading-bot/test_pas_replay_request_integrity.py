"""Unsigned PAS replay integrity: rejected reads must not consume future data."""
from copy import deepcopy
import pytest
from exchange.base_exchange import ExchangeError
from exchange.replay import ReplayTape, checksum

NOW = 1_791_849_600_000


def tape_for(payload):
    body = dict(schema_version=1, cycles=1, clock_model='RECORDED_LOGICAL_CLOCK',
                parameters={}, provenance='SYNTHETIC_PAS_REQUEST_INTEGRITY',
                operations=[dict(kind='info', payload=deepcopy(payload),
                                 response={'recorded': 'PAS_ONLY'}),
                            dict(kind='clock', value=NOW)])
    return ReplayTape(dict(body, sha256=checksum(body)))


@pytest.mark.parametrize('recorded,wrong', [
    ({'type': 'meta', 'dex': 'pas'}, {'type': 'meta', 'dex': 'par'}),
    ({'type': 'l2Book', 'coin': 'pas:BTC'}, {'type': 'l2Book', 'coin': 'pas:EWY'}),
    ({'type': 'l2Book', 'coin': 'pas:EWY'}, {'type': 'l2Book', 'coin': 'BTC'}),
    ({'type': 'candleSnapshot', 'req': {'coin': 'pas:BTC', 'startTime': 100}},
     {'type': 'candleSnapshot', 'req': {'coin': 'pas:BTC', 'startTime': 101}}),
])
def test_pas_replay_request_mismatch_preserves_event_and_future_clock(recorded, wrong):
    tape = tape_for(recorded)
    for _ in range(2):
        with pytest.raises(ExchangeError, match='REPLAY_REQUEST_MISMATCH_NO_FUTURE_DATA'):
            tape(wrong)
        assert tape.cursor == 0
        assert tape.previous_clock == -1
        with pytest.raises(ExchangeError, match='REPLAY_UNCONSUMED_OPERATIONS'):
            tape.finish()
    assert tape(recorded) == {'recorded': 'PAS_ONLY'}
    assert tape.clock_ms() == NOW
    assert tape.finish()['consumed_operations'] == 2
