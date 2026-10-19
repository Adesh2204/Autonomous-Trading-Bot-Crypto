"""Validate retained operator-reviewed organizer provenance, never infer a roster."""
from pathlib import Path
import json
from .base_exchange import ExchangeError
from .long_session import sha
from .testnet_certification import TEAM


def registration_evidence(directory,now_ms):
    directory=Path(directory).resolve();p=directory/'organizer_confirmation.json'
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
