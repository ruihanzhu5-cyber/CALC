import json
import subprocess
import sys


def test_module_entrypoint_executes_the_requested_command():
    completed = subprocess.run([sys.executable, "-m", "calc.cli", "doctor"],
                               capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    assert result["httpx"] and result["model_requests_made"] == 0
