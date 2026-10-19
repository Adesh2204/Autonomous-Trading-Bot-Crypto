"""Opt-in pytest safety boundary for the PAS PR2 offline review suite.

Load with `python -m pytest -p offline_no_sign ...`. Historical signed-fixture
suites are intentionally separate and are not executed by this job.
"""
import pytest


@pytest.fixture(autouse=True)
def prohibit_network_and_signatures(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('OFFLINE_NO_SIGN_SUITE: network/signing prohibited')

    import socket
    import requests
    import hyperliquid.utils.signing as signing
    from eth_account import Account
    from eth_account.signers.local import LocalAccount

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)
    for name in dir(signing):
        if name.startswith('sign_') and callable(getattr(signing, name)):
            monkeypatch.setattr(signing, name, forbidden)
    for owner in (Account, LocalAccount):
        for name in ('sign_message', 'sign_transaction', 'sign_typed_data', 'unsafe_sign_hash'):
            if hasattr(owner, name):
                monkeypatch.setattr(owner, name, forbidden)
