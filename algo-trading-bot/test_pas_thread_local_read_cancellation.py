"""Thread-local cancellation must isolate stream repair from unrelated reads."""
import threading

from exchange.hyperliquid_client import HyperliquidClient, RequestsInfoTransport


class RecordingTransport(RequestsInfoTransport):
    """Observe the cancellation token handed to a read without doing I/O."""
    def __init__(self):
        self.cancel_events = []

    def __call__(self, payload, *, cancel_event=None, progress=None):
        self.cancel_events.append(cancel_event)
        return {}


def test_repair_cancellation_is_thread_local_and_nested_scopes_restore():
    transport = RecordingTransport()
    client = HyperliquidClient(transport=transport)
    default_event = threading.Event()
    repair_event = threading.Event()
    nested_event = threading.Event()
    repair_event.set()
    client.read_cancel_event = default_event

    repair_ready = threading.Event()
    account_done = threading.Event()
    observed = {}
    failures = []

    def repair_thread():
        try:
            with client.read_cancellation(repair_event):
                assert client.read_cancel_event is repair_event
                with client.read_cancellation(nested_event):
                    assert client.read_cancel_event is nested_event
                assert client.read_cancel_event is repair_event
                repair_ready.set()
                if not account_done.wait(3):
                    raise AssertionError('account read did not finish')
            assert client.read_cancel_event is default_event
        except BaseException as exc:
            failures.append(exc)
            repair_ready.set()

    def account_thread():
        try:
            if not repair_ready.wait(3):
                raise AssertionError('repair thread did not enter cancellation scope')
            observed['before'] = client.read_cancel_event
            client.post_info('userAbstraction', user='0xoffline-test')
            observed['after'] = client.read_cancel_event
        except BaseException as exc:
            failures.append(exc)
        finally:
            account_done.set()

    repair = threading.Thread(target=repair_thread, name='test-repair')
    account = threading.Thread(target=account_thread, name='test-account-read')
    repair.start()
    account.start()
    repair.join(4)
    account.join(4)

    assert not repair.is_alive()
    assert not account.is_alive()
    assert failures == []
    assert observed == {'before': default_event, 'after': default_event}
    assert transport.cancel_events == [default_event]
    assert client.read_cancel_event is default_event
