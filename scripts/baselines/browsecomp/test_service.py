"""Offline exact-response/cache concurrency checks, using the BCP environment."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import unittest

from service import create_app


class ServiceContract(unittest.TestCase):
    def test_exact_rendering_and_concurrent_request_coalescing(self):
        class Searcher:
            searches = reads = 0

            def search(self, query, k):
                self.searches += 1
                return [{"docid": "doc", "text": "Title\nabcdefghijk"}]

            def get_document(self, docid):
                self.reads += 1
                return {"docid": docid, "text": "Title\nabcdefghijk"}

        class Tokenizer:
            def encode(self, text, **kwargs):
                return list(text)

            def decode(self, ids, **kwargs):
                return "".join(ids)

        searcher = Searcher()
        app = create_app(searcher, Tokenizer(), source_root=Path("."), tokenizer_revision="fixture",
                         snippet_tokens=3, document_tokens=8)
        endpoints = {route.path: route.endpoint for route in app.routes}

        def probe(_):
            return (endpoints["/retrieve"](SimpleNamespace(query="same")),
                    endpoints["/document"](SimpleNamespace(docid="doc")))

        with ThreadPoolExecutor(19) as pool:
            results = list(pool.map(probe, range(19)))
        self.assertEqual(searcher.searches, 1)
        self.assertEqual(searcher.reads, 1)
        self.assertTrue(all(row == results[0] for row in results))
        self.assertEqual(results[0][0], {"result": [{"docid": "doc", "document": {"title": "Title", "text": "abc"}}]})
        self.assertEqual(results[0][1], {"document": {"docid": "doc", "title": "Title", "text": "abcdefgh"}, "truncated": True})


if __name__ == "__main__":
    unittest.main()
