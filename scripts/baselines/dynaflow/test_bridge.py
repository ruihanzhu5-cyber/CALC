"""Contract checks with local HTTP fixtures, not benchmark results."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from bridge import ToolBridge
from prepare_inputs import config, questions


class BridgeTest(unittest.TestCase):
    def test_real_http_protocol_and_full_document(self):
        calls = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, payload))
                result = ({"result": [{"docid": "d1", "document": {"title": "T", "text": "snippet"}}]}
                          if self.path == "/retrieve" else
                          {"document": {"docid": "d1", "title": "T", "text": "raw document original text"}, "truncated": False})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

        with tempfile.TemporaryDirectory() as temp:
            upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
            bridge = ToolBridge(f"http://127.0.0.1:{upstream.server_port}", Path(temp) / "audit.jsonl", "test-token")
            server = bridge.server(port=0)
            for item in [upstream, server]:
                threading.Thread(target=item.serve_forever, daemon=True).start()
            try:
                def execute(name, arguments, token="test-token"):
                    request = Request(f"http://127.0.0.1:{server.server_port}/execute",
                                      data=json.dumps({"name": name, "arguments": arguments, "task_id": "q1", "dataset": "BrowseComp-Plus"}).encode(),
                                      headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
                    with build_opener(ProxyHandler({})).open(request) as response:
                        return json.load(response)

                self.assertEqual(execute("search", {"query": "question"})["result"][0]["docid"], "d1")
                self.assertEqual(execute("get_document", {"docid": "d1"})["document"]["text"], "raw document original text")
                self.assertTrue(execute("get_document", {"url": "fake"})["is_error"])
                with self.assertRaises(HTTPError) as error:
                    execute("search", {"query": "question"}, token="wrong")
                self.assertEqual(error.exception.code, 401)
                self.assertEqual(calls, [("/retrieve", {"query": "question"}), ("/document", {"docid": "d1"})])
                audit = (Path(temp) / "audit.jsonl").read_text()
                self.assertIn("raw document original text", audit)
                self.assertNotIn("test-token", audit)
            finally:
                for item in [server, upstream]:
                    item.shutdown()
                    item.server_close()

    def test_allowlist_and_native_thinking_protocol(self):
        from dynaflow.configuration import normalize, request, validate
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "tasks.jsonl"
            source.write_text(json.dumps({"query_id": "q1", "query": "Question?", "answer": "DO_NOT_PASS", "qrels": ["secret"]}))
            rows = questions(source)
            self.assertEqual(set(rows[0]), {"number", "dataset", "task_id", "Question"})
            self.assertNotIn("DO_NOT_PASS", json.dumps(rows))
        cfg = normalize(config())
        cfg["question_order"] = [1]
        validate(cfg, 1)
        messages = [{"role": "assistant", "content": "", "reasoning_content": "retained"}]
        for role in ["main", "subagent"]:
            body = request(cfg, messages, role)
            self.assertEqual(body["model"], "deepseek-flash")
            self.assertEqual(body["thinking"], {"type": "enabled"})
            self.assertEqual(body["reasoning_effort"], "high")
            self.assertEqual(body["messages"][0]["reasoning_content"], "retained")
            self.assertNotIn("temperature", body)


if __name__ == "__main__":
    unittest.main()
