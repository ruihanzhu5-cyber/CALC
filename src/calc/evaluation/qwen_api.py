"""BC+ answer judging via a Qwen3-32B API, using the pinned official protocol.

This changes model transport, not the original grading prompt or answer parser.
It does not claim hosted inference is bit-identical to the upstream vLLM run.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx

from calc.evaluation.bcp_official_protocol import create_judge_prompt, parse_judge_response
from calc.llm import OpenAICompatibleClient


SOURCE_COMMIT = "046949032b0328319cc9a02663a759ec601d9402"


def judge_record(record: dict, truth: dict, client: OpenAICompatibleClient) -> dict[str, Any]:
    qid = str(record["query_id"])
    if qid != str(truth["query_id"]):
        raise ValueError("Run and scoring-side reference query IDs differ")
    parts = record.get("result") or []
    answer = parts[-1].get("output", "") if parts and parts[-1].get("type") == "output_text" else ""
    result: dict[str, Any] = {
        "query_id": qid, "status": "incomplete_agent_response", "judge_called": False,
        "is_completed": record.get("status") == "completed", "response": answer,
        "judge_result": {"parse_error": True, "error": "Response incomplete or cannot be parsed"},
        "protocol_commit": SOURCE_COMMIT, "transport": "Qwen3-32B API",
    }
    # This matches the official evaluator's incomplete-response branch.
    if not result["is_completed"] or not isinstance(answer, str) or not answer.strip():
        return result
    prompt = create_judge_prompt(truth["query"], answer, truth["answer"])
    result.update(judge_called=True, judge_prompt=prompt)
    try:
        response = client.complete([{"role": "user", "content": prompt}], max_output_tokens=4096)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        result.update(status="judge_transport_error", error_type=type(exc).__name__)
        return result
    text = response.message.get("content") or ""
    parsed = parse_judge_response(text)
    result.update(judge_response=text, judge_result=parsed, usage=response.usage.to_dict(),
                  finish_reason=response.finish_reason)
    result["status"] = "judged" if not parsed["parse_error"] and response.finish_reason == "stop" else "judge_output_error"
    return result


def summarize(results: list[dict]) -> dict:
    errors = sum(item["status"] in {"judge_transport_error", "judge_output_error"} for item in results)
    return {
        "evaluation": "complete" if not errors else "incomplete_judge_errors",
        "protocol_commit": SOURCE_COMMIT, "transport": "Qwen3-32B API",
        "num_tasks": len(results), "num_judge_errors": errors,
        "num_judge_calls": sum(item["judge_called"] for item in results),
        "num_incomplete_agent_responses": sum(item["status"] == "incomplete_agent_response" for item in results),
        "Accuracy (%)": round(100 * sum(item["judge_result"].get("correct", False) is True
                                        for item in results) / len(results), 2) if results and not errors else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--execute", action="store_true", help="Call the judge API; default checks configuration only")
    parser.add_argument("--probe", action="store_true", help="Check authenticated model availability without generation")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    key_env = config.get("api_key_env", "BCP_JUDGE_API_KEY")
    key = os.environ.get(key_env)
    configured = bool(key and config.get("base_url", "").startswith(("https://", "http://")))
    if args.probe:
        if not configured:
            raise ValueError("Configure the Qwen endpoint and API key before probing")
        try:
            with httpx.Client(timeout=60) as http:
                response = http.get(config["base_url"].rstrip("/") + "/models",
                                    headers={"Authorization": f"Bearer {key}"})
                response.raise_for_status()
                available = {item["id"] for item in response.json()["data"]}
            probe = {"authenticated": True, "requested_model": config["model"],
                     "model_available": config["model"] in available, "generation_calls": 0,
                     "qwen3_32b_candidates": sorted(item for item in available if "qwen3-32b" in item.lower())}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            probe = {"authenticated": False, "error_type": type(exc).__name__, "generation_calls": 0}
            if isinstance(exc, httpx.HTTPStatusError):
                probe["http_status"] = exc.response.status_code
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / "model_availability.json").write_text(json.dumps(probe, indent=2), encoding="utf-8")
        print(json.dumps(probe, indent=2))
        return int(not probe.get("model_available", False))
    if not args.execute:
        print(json.dumps({"configuration_ready": configured, "model": config["model"],
                          "credential_present": bool(key), "model_calls": 0,
                          "protocol_commit": SOURCE_COMMIT}, indent=2))
        return 0
    if not configured:
        raise ValueError("Configure the Qwen endpoint and its API key environment variable before executing")
    if config["model"].lower().split("/")[-1] != "qwen3-32b":
        raise ValueError("This protocol expects Qwen3-32B, not another Qwen generation or size")
    if not all((args.input_dir, args.ground_truth, args.output_dir)):
        raise ValueError("--input-dir, --ground-truth and --output-dir are required with --execute")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError("Use a new evaluation directory; existing judge calls are not silently repeated")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    truth = {}
    for line in args.ground_truth.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            row = json.loads(line)
            truth[str(row["query_id"])] = row
    inputs = sorted(args.input_dir.glob("*.json"))
    records = [(path, json.loads(path.read_text(encoding="utf-8-sig"))) for path in inputs]
    ids = [str(record["query_id"]) for _, record in records]
    if not ids or len(set(ids)) != len(ids) or set(ids) - truth.keys():
        raise ValueError("Require nonempty unique query IDs with scoring-side references")
    manifest = {
        "started_at": datetime.now(UTC).isoformat(), "model": config["model"], "base_url": config["base_url"],
        "protocol_commit": SOURCE_COMMIT, "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                           for p, _ in records},
        "sampling": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "max_tokens": 4096, "enable_thinking": False},
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    client = OpenAICompatibleClient(config["base_url"], config["model"], key, timeout=180, temperature=0.7,
                                   extra_body={"top_p": 0.8, "top_k": 20, "enable_thinking": False})
    results = []
    try:
        for path, record in records:
            result = judge_record(record, truth[str(record["query_id"])], client)
            results.append(result)
            (args.output_dir / f"{path.stem}_eval.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        client.close()
    summary = summarize(results)
    (args.output_dir / "evaluation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return int(summary["num_judge_errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
