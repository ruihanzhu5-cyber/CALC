"""Windows pythonw host: no console attachment; systemd owns Linux actors."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
import winreg


def linux(path):
    path = Path(path).resolve()
    if path.drive.lower() != 'd:':
        raise ValueError('Experiment files must stay on D:')
    return '/mnt/d/' + path.as_posix()[3:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--unit', required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding='utf-8-sig'))
    if not cfg['output_dir'].startswith('/mnt/d/CALC-experiments/runs/'):
        raise ValueError('Expected D: experiment directory')
    root = Path('D:/' + cfg['output_dir'][7:])
    receipt = {'host_pid': os.getpid(), 'started_at': datetime.now(timezone.utc).isoformat(),
               'status': 'starting', 'host': 'pythonw without console / WSL systemd',
               'unit': args.unit, 'automatic_restart': False}
    path = root / 'launch_receipt.json'
    with path.open('x', encoding='utf-8') as file:
        json.dump(receipt, file, indent=2)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as registry:
            credential = winreg.QueryValueEx(registry, 'DEEPSEEK_API_KEY')[0]
        env = dict(os.environ)
        env['DEEPSEEK_API_KEY'] = credential
        inherited = [part for part in env.get('WSLENV', '').split(':')
                     if part and part.split('/')[0] != 'DEEPSEEK_API_KEY']
        env['WSLENV'] = ':'.join([*inherited, 'DEEPSEEK_API_KEY'])
        script = Path(__file__).with_name('run_gaia2_service.py')
        command = ['wsl.exe', '-d', 'CALC-Research', '--', '/opt/calc/envs/gaia2/bin/python',
                   '-B', linux(script), '--config', linux(args.config), '--plan', linux(args.plan), '--unit', args.unit]
        with (root / 'batch.host.log').open('w', encoding='utf-8') as log:
            child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            receipt.update(status='running', wsl_host_pid=child.pid)
            path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            code = child.wait()
        receipt.update(status='finished' if code == 0 else 'failed', exit_code=code)
    except Exception as exc:
        receipt.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        receipt['updated_at'] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
