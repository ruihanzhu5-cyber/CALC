"""Launch one explicit paid batch as a non-restarting systemd service.

Environment credentials stay in a root-only /run file until systemd has started
the service. Neither command arguments nor receipts contain their values.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True, type=Path)
    p.add_argument('--plan', required=True, type=Path)
    p.add_argument('--unit', required=True)
    args = p.parse_args()
    if not re.fullmatch(r'calc-gaia2-[a-z0-9-]+', args.unit):
        raise ValueError('Invalid service unit name')
    root = Path(json.loads(args.config.read_text())['output_dir'])
    if (root / 'execute_queue.json').exists() or (root / 'service_receipt.json').exists():
        raise FileExistsError('Paid batch already launched; no automatic restart')
    repo = Path(__file__).resolve().parents[1]
    key = os.environ['DEEPSEEK_API_KEY']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', key):
        raise ValueError('Unsupported credential encoding')
    descriptor, name = tempfile.mkstemp(prefix='calc-gaia2-', suffix='.env', dir='/run')
    try:
        with os.fdopen(descriptor, 'w') as file:
            file.write('DEEPSEEK_API_KEY=' + key + '\n')
        command = ['systemd-run', '--unit=' + args.unit, '--property=Type=exec', '--property=Restart=no',
            '--property=KillMode=control-group', '--property=WorkingDirectory=' + str(repo),
            '--property=EnvironmentFile=' + name,
            '--property=StandardOutput=append:' + str(root / 'actor-service.log'),
            '--property=StandardError=inherit', '--setenv=PYTHONDONTWRITEBYTECODE=1',
            '--setenv=TMPDIR=/opt/calc/tmp', '--setenv=HF_HOME=/opt/calc/cache/huggingface',
            '--setenv=XDG_CACHE_HOME=/opt/calc/cache', '/opt/calc/envs/gaia2/bin/python', '-u',
            str(repo / 'scripts/run_gaia2_batch.py'), '--config', str(args.config),
            '--plan', str(args.plan), '--execute']
        with (root / 'service_receipt.json').open('x') as receipt:
            json.dump({'unit': args.unit, 'launcher_pid': os.getpid(),
                       'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                       'restart': 'no', 'config': str(args.config), 'plan': str(args.plan)}, receipt, indent=2)
        subprocess.run(command, check=True)
    finally:
        os.unlink(name)
    # Keep a host WSL session while systemd independently owns the process tree.
    while subprocess.check_output(['systemctl', 'show', args.unit, '-p', 'ActiveState', '--value'],
                                  text=True).strip() in {'active', 'activating', 'deactivating'}:
        time.sleep(2)
    status = subprocess.check_output(['systemctl', 'show', args.unit, '-p', 'ExecMainStatus', '--value'], text=True)
    raise SystemExit(int(status.strip()))


if __name__ == '__main__':
    main()
