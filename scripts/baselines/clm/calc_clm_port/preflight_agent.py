"""Real Harbor/ContextEnv smoke agent. Never calls a language model or grades BCP."""
from __future__ import annotations

import json
from pathlib import Path
from harbor.agents.base import BaseAgent
from clm_harness.clm_agent.harness import ClmAgent


class ContextPreflightAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "clm-context-preflight-no-model"

    def version(self) -> str:
        return "0.1"

    def __init__(self, logs_dir: Path, model_name=None, **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)
        self.author_agent = ClmAgent(
            logs_dir=logs_dir, model_name="openai/offline-no-model",
            context_budget_tokens=28672, cost_metric="usd", max_steps=1,
            send_chat_template_kwargs=False,
        )

    async def setup(self, environment) -> None:
        await self.author_agent.setup(environment)

    async def run(self, instruction, environment, context) -> None:
        messages = [
            {"role": "system", "content": "Pinned offline smoke system"},
            {"role": "user", "content": "Pinned offline smoke task; not the research question"},
            {"role": "assistant", "content": "OLD_INFORMATION_SENTINEL"},
        ]
        command = (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "p=Path('/tmp/.live_ctx/LIVE_CTX_MAIN.txt')\n"
            "p.write_text(p.read_text().replace('OLD_INFORMATION_SENTINEL','NEW_NOTE'))\n"
            "PY"
        )
        result = await self.author_agent._ctx.step(command, messages, environment=environment)
        assert result.result.return_code == 0
        assert "NEW_NOTE" in json.dumps(messages)
        assert "OLD_INFORMATION_SENTINEL" not in json.dumps(messages)
        (self.logs_dir / "offline_preflight.json").write_text(json.dumps({
            "kind": "offline_context_environment_preflight", "model_calls": 0,
            "benchmark_evaluation": "not_run", "author_context_edit_applied": True,
        }) + "\n")
        self.author_agent._host_mirror.unlink(missing_ok=True)
