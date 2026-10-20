"""Copy retained human account identity evidence; never create action acceptance."""
from pathlib import Path
import json
import shutil

from .base_exchange import ExchangeError
from .paper_operations import atomic_json
from .long_session import sha


def copy_confirmation(path, output):
    source=Path(path).resolve();record=json.loads(source.read_text())
    relative=Path(record.get('original_request_file','missing'))
    raw=(source.parent/relative).resolve()
    if (relative.is_absolute() or '..' in relative.parts or relative.suffix!='.txt'
            or not raw.is_relative_to(source.parent) or (source.parent/relative).is_symlink() or not raw.is_file()
            or sha(raw)!=record.get('original_request_sha256')):
        raise ExchangeError('RETAINED_DIRECT_OPERATOR_REQUEST_REQUIRED')
    output=Path(output);target=output/'original_operator_request.txt'
    shutil.copyfile(raw,target);record['original_request_file']=target.name
    atomic_json(output/'operator_confirmation.json',record)
