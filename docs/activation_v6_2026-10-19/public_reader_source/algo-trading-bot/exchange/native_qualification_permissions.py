"""Practice qualification calendar/provenance checks; no execution authority."""
from pathlib import Path
import hashlib,json
from .base_exchange import ExchangeError
from .competition_windows import WINDOWS


def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def practice_permission(team,starts_ms,expires_ms,*,path=None):
    """An unpublished practice interval needs its original organizer permission.

    This validates scope and operator-reviewed provenance, not arbitrary text's
    authenticity. A scored calendar date cannot automatically authorize par.
    No permission file creates the separate exact API-wallet approval.
    """
    if (type(starts_ms) is not int or type(expires_ms) is not int or starts_ms>=expires_ms):
        raise ExchangeError('FINITE_NATIVE_PRACTICE_PERMISSION_INTERVAL_REQUIRED')
    begin,end,_=WINDOWS[0]
    if begin<=starts_ms<expires_ms<=end:
        return dict(basis='PUBLISHED_PRACTICE_WINDOW_NOT_TEAM_ELIGIBILITY_CERTIFICATE',
            starts_ms=begin,expires_ms=end,files={})
    if path is None:raise ExchangeError('ORGANIZER_PRACTICE_QUALIFICATION_PERMISSION_REQUIRED')
    try:
        path=Path(path).resolve();record=json.loads(path.read_text())
        relative=Path(record.get('original_record_file','missing'))
        raw=(path.parent/relative).resolve()
        if (relative.is_absolute() or '..' in relative.parts or relative.suffix not in {'.eml','.txt','.json'}
                or not raw.is_relative_to(path.parent) or not raw.is_file()
                or _sha(raw)!=record.get('original_record_sha256')
                or record.get('network')!='testnet' or record.get('dex')!='par'
                or record.get('symbol')!='par:BTC' or record.get('supervised_native_qualification') is not True
                or record.get('team_wallet','').lower()!=team.lower()
                or record.get('operator_reviewed_provenance') is not True
                or not isinstance(record.get('source_reference'),str) or not record['source_reference'].strip()
                or type(record.get('starts_ms')) is not int or type(record.get('expires_ms')) is not int
                or not record['starts_ms']<=starts_ms<expires_ms<=record['expires_ms']):
            raise ExchangeError('APPLICABLE_ORIGINAL_PAR_NATIVE_PERMISSION_REQUIRED')
        return dict(basis='ORIGINAL_ORGANIZER_RECORD_REVIEWED_FOR_THIS_PRACTICE_TEST',
            starts_ms=record['starts_ms'],expires_ms=record['expires_ms'],
            files={str(path):_sha(path),str(raw):_sha(raw)})
    except (OSError,ValueError,TypeError,KeyError) as exc:
        raise ExchangeError('APPLICABLE_ORIGINAL_PAR_NATIVE_PERMISSION_REQUIRED') from exc


def require_bound_permission(binding,now_ms):
    try:
        valid=(type(now_ms) is int and binding['starts_ms']<=now_ms<binding['expires_ms']
            and all(_sha(path)==expected for path,expected in binding['files'].items()))
    except (OSError,KeyError,TypeError,ValueError):valid=False
    if not valid:raise ExchangeError('NATIVE_PRACTICE_PERMISSION_EXPIRED_OR_CHANGED')
