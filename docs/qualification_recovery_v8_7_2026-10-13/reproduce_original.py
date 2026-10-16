"""Execute the three repaired fixture regressions against the preserved original module."""
from pathlib import Path
import sys,types,pytest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'algo-trading-bot'))
old=types.ModuleType('exchange.qualification_original');old.__package__='exchange'
path=Path(__file__).resolve().parent/'source_before/testnet_qualification.py'
exec(compile(path.read_text(),str(path),'exec'),old.__dict__)
class OriginalModulePlugin:
 def pytest_collection_modifyitems(self,items):
  for item in items:item.module.module=old
raise SystemExit(pytest.main(['algo-trading-bot/test_qualification_recovery_v8_7.py','-q','--tb=short','--junitxml=docs/qualification_recovery_v8_7_2026-10-13/reproduced_defects_v3.xml'],plugins=[OriginalModulePlugin()]))
