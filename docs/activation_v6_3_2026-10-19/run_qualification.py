"""Driver to run fresh native qualification with human-approved proposal."""
import os, sys, json, time, shutil, pty, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUAL_DIR = ROOT / 'docs/activation_v6_3_2026-10-19/qualification'
OPERATOR_CONF = ROOT / 'docs/activation_v6_2026-10-19/operator_identity/operator_confirmation.json'
TRADING_ISO = ROOT / 'docs/activation_v6_3_2026-10-19/trading_isolation/policy.json'
RELEASE = ROOT / 'docs/activation_v6_3_2026-10-19/regression_release_final/test_receipt.json'
PYTHON = sys.executable

if QUAL_DIR.exists():
    shutil.rmtree(QUAL_DIR)

print("[1/3] Running native-prepare...")
cmd_prep = [
    PYTHON, str(ROOT / 'scripts/anchorium_cli.py'), 'native-prepare',
    '--output', str(QUAL_DIR),
    '--operator-confirmation', str(OPERATOR_CONF),
    '--trading-isolation-policy', str(TRADING_ISO)
]
p_prep = subprocess.run(cmd_prep, cwd=ROOT, capture_output=True, text=True)
if p_prep.returncode != 0:
    print("native-prepare failed:")
    print(p_prep.stdout)
    print(p_prep.stderr)
    sys.exit(1)

prop = json.loads((QUAL_DIR / 'qualification_proposal.json').read_text())
proposal_hash = prop['proposal_hash']
phrase = 'APPROVE PAS QUALIFICATION ' + proposal_hash
print(f"[2/3] Approving qualification proposal {proposal_hash} via interactive PTY...")

cmd_appr = [
    PYTHON, str(ROOT / 'scripts/anchorium_cli.py'), 'native-approve',
    '--proposal', str(QUAL_DIR / 'qualification_proposal.json'),
    '--discovery', str(QUAL_DIR / 'fresh_discovery/discovery.json'),
    '--release', str(RELEASE),
    '--output', str(QUAL_DIR / 'acceptance.json')
]

master, slave = pty.openpty()
p_appr = subprocess.Popen(cmd_appr, cwd=ROOT, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
os.close(slave)
os.write(master, phrase.encode() + b'\n')
out_appr, err_appr = p_appr.communicate()
os.close(master)

if p_appr.returncode != 0:
    print("native-approve failed:")
    print(out_appr.decode())
    print(err_appr.decode())
    sys.exit(1)

print("native-approve succeeded:")
print(out_appr.decode())

print("[3/3] Executing native qualification on PAS testnet...")
exec_dir = QUAL_DIR / 'execution'
cmd_exec = [
    PYTHON, str(ROOT / 'scripts/anchorium_cli.py'), 'native-execute',
    '--proposal', str(QUAL_DIR / 'qualification_proposal.json'),
    '--discovery', str(QUAL_DIR / 'fresh_discovery/discovery.json'),
    '--release', str(RELEASE),
    '--acceptance', str(QUAL_DIR / 'acceptance.json'),
    '--output', str(exec_dir)
]

p_exec = subprocess.run(cmd_exec, cwd=ROOT, capture_output=True, text=True)
print("native-execute return code:", p_exec.returncode)
print(p_exec.stdout)
if p_exec.stderr:
    print(p_exec.stderr)

if p_exec.returncode != 0:
    sys.exit(1)

print("PAS qualification finished successfully!")

