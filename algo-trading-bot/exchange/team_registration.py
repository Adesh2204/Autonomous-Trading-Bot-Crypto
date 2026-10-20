"""Validate retained operator-reviewed organizer provenance, never infer a roster."""
from pathlib import Path
import json
from .base_exchange import ExchangeError
from .long_session import sha
from .testnet_certification import TEAM


def registration_evidence(directory,now_ms,*,scope='TRADING'):
    directory=Path(directory).resolve();p=directory/'organizer_confirmation.json'
    if not p.exists() and (directory/'operator_confirmation.json').exists():
        return operator_account_evidence(directory,now_ms)
    try:
        record=json.loads(p.read_text());relative=Path(record.get('original_record_file','missing'))
        raw=(directory/relative).resolve()
        if (relative.is_absolute() or '..' in relative.parts or not raw.is_relative_to(directory)
                or relative.suffix not in {'.eml','.txt','.json'} or not raw.is_file()
                or sha(raw)!=record.get('original_record_sha256')
                or record.get('operator_reviewed_provenance') is not True
                or record.get('team_wallet','').lower()!=TEAM.lower()
                or record.get('network')!='testnet' or record.get('dex')!='pas' or record.get('collateral')!='USDP'
                or not isinstance(record.get('source_reference'),str) or not record['source_reference'].strip()
                or type(record.get('starts_ms')) is not int or type(record.get('expires_ms')) is not int
                or not record['starts_ms']<=now_ms<record['expires_ms']):
            raise ExchangeError('REGISTERED_TEAM_ORGANIZER_RECORD_REQUIRED')
    except (OSError,ValueError,TypeError):
        raise ExchangeError('REGISTERED_TEAM_ORGANIZER_RECORD_REQUIRED') from None
    return dict(team_wallet=TEAM,status='OPERATOR_REVIEWED_ORGANIZER_RECORD',
        record_sha256=sha(p),original_record_sha256=sha(raw),source_reference=record['source_reference'],
        limitation='Human review attests provenance; software hashes cannot establish organizer authorship')


def operator_account_evidence(directory,now_ms):
    """Direct named-wallet confirmation, explicitly narrower than trading consent.

    The retained human request is not relabeled as an organizer message, an
    exchange receipt, or an acceptance of a subsequently generated action plan.
    The funded account, local signer and genuine plan approval are checked again.
    """
    directory=Path(directory).resolve();p=directory/'operator_confirmation.json'
    try:
        record=json.loads(p.read_text());relative=Path(record['original_request_file'])
        raw=(directory/relative).resolve()
        if (record.get('basis')!='DIRECT_HUMAN_V6_ACCOUNT_CONFIRMATION'
                or record.get('scope')!='ACCOUNT_IDENTITY_ONLY' or record.get('operator_confirmed_named_wallet') is not True
                or record.get('team_wallet','').lower()!=TEAM.lower()
                or record.get('network')!='testnet' or record.get('dex')!='pas' or record.get('collateral')!='USDP'
                or relative.is_absolute() or '..' in relative.parts or relative.suffix!='.txt'
                or not raw.is_relative_to(directory) or not raw.is_file() or (directory/relative).is_symlink()
                or sha(raw)!=record.get('original_request_sha256')
                or type(record.get('starts_ms')) is not int or type(record.get('expires_ms')) is not int
                or not record['starts_ms']<=now_ms<record['expires_ms']
                or not isinstance(record.get('source_reference'),str) or not record['source_reference'].strip()):
            raise ExchangeError('DIRECT_OPERATOR_ACCOUNT_IDENTITY_REQUIRED')
    except (OSError,ValueError,KeyError,TypeError):
        raise ExchangeError('DIRECT_OPERATOR_ACCOUNT_IDENTITY_REQUIRED') from None
    return dict(team_wallet=TEAM,status='DIRECT_OPERATOR_CONFIRMED_ACCOUNT_IDENTITY',
        record_sha256=sha(p),original_request_sha256=sha(raw),source_reference=record['source_reference'],
        scope='ACCOUNT_IDENTITY_ONLY',limitation='Human named-wallet confirmation only; organizer authorship, funding receipt, exact configuration approval and trading consent are separate facts.')
