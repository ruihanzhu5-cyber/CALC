"""Durable two-method supervisor. Explicit locked tasks, one attempt per task."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True, type=Path)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--methods', nargs='+', choices=['calc', 'manta'])
    p.add_argument('--tasks', nargs='+')
    p.add_argument('--queue-name')
    args = p.parse_args()
    config = json.loads(args.config.read_text())
    ids = json.loads(Path(config['task_lock']).read_text())['task_ids']
    if args.tasks:
        if len(set(args.tasks)) != len(args.tasks) or not set(args.tasks) <= set(ids):
            raise ValueError('Explicit task subset must contain unique locked task IDs')
        ids = args.tasks
    root = Path(config['output_dir'])
    root.mkdir(parents=True, exist_ok=True)
    phase = 'execute' if args.execute else 'preflight'
    queue_name = args.queue_name or (phase + '_queue.json')
    if Path(queue_name).name != queue_name:
        raise ValueError('Queue name must be a filename')
    status_path = root / queue_name
    if args.execute and status_path.exists():
        raise FileExistsError('refusing to restart an existing paid batch')
    lock = threading.Lock()
    methods = args.methods or (['calc', 'manta'] if args.execute else ['calc'])
    state = {'pid': os.getpid(), 'phase': phase,
             'tasks': {method + '/' + task: {'status': 'queued'} for method in methods for task in ids},
             'heartbeat': time.time()}
    def save():
        temp = status_path.with_suffix('.tmp')
        temp.write_text(json.dumps(state, indent=2))
        temp.replace(status_path)
    def method_worker(method):
        for task in ids:
            cmd = [sys.executable, '-B', str(Path(__file__).with_name('run_gaia2_pilot.py')),
                '--config', str(args.config), '--method', method, '--task', task]
            if args.execute:
                cmd.append('--execute')
            key = method + '/' + task
            with (root / f'{phase}.{method}.{task}.log').open('w') as logfile:
                child = subprocess.Popen(cmd, stdout=logfile, stderr=subprocess.STDOUT)
                with lock:
                    state['tasks'][key] = {'status': 'running', 'pid': child.pid}
                    save()
                while child.poll() is None:
                    time.sleep(2)
                    with lock:
                        state['heartbeat'] = time.time()
                        save()
                with lock:
                    state['tasks'][key].update(status='finished' if child.returncode == 0 else 'failed',
                                              exit_code=child.returncode)
                    save()
                if child.returncode:
                    return  # don't spend on further tasks after an execution/configuration fault
    with ThreadPoolExecutor(max_workers=2 if args.execute else 1) as pool:
        # Both methods share the exact adapter; one preflight per environment is sufficient.
        list(pool.map(method_worker, methods))
    state['finished'] = True
    state['all_tasks_executed'] = all(t['status'] == 'finished' for t in state['tasks'].values())
    save()
    if not state['all_tasks_executed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
