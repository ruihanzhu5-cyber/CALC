"""Shared official BM25 retriever/document-reader for controlled BCP experiments.

All data, model-tokenizer cache, and logs belong under the experiment directory.
The source loader reads the official BM25Searcher without importing optional
dense-retriever modules. No query labels, qrels, model weights, or LLM APIs needed.
"""
import argparse
from collections import OrderedDict
import hashlib
import importlib.util
import os
import sys
import threading
import types
from pathlib import Path

SOURCE_COMMIT = "046949032b0328319cc9a02663a759ec601d9402"
INDEX_REVISION = "b3f37f70c33829eb09d04784a54277a31871fd63"
EXP_ROOT = Path(os.environ.get("CALC_EXP_ROOT", "D:/CALC-experiments" if os.name == "nt" else "/mnt/d/CALC-experiments"))


def load_official_bm25(source_root: Path):
    """Load only the official base.py and bm25_searcher.py from a pinned checkout."""
    package_dir = source_root / "searcher" / "searchers"
    for name in ("base.py", "bm25_searcher.py"):
        if not (package_dir / name).is_file():
            raise FileNotFoundError(f"Missing official source: {package_dir / name}")
    package_name = "calc_bcp_official_searchers"
    package = types.ModuleType(package_name)
    package.__path__ = [str(package_dir)]
    sys.modules[package_name] = package
    for stem in ("base", "bm25_searcher"):
        spec = importlib.util.spec_from_file_location(f"{package_name}.{stem}", package_dir / f"{stem}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{package_name}.bm25_searcher"].BM25Searcher


def split_title(raw: str) -> tuple[str, str]:
    # Same content shape as the official REST server: docid, title and text.
    if raw.startswith("---\ntitle:"):
        lines = raw.split("\n")
        title = lines[1].removeprefix("title:").strip().strip('"')
        return title, "\n".join(lines[2:])
    lines = raw.split("\n")
    return (lines[0].strip('"') if lines else ""), "\n".join(lines[1:])


def create_app(searcher, tokenizer, *, source_root: Path, tokenizer_revision: str,
               k: int = 10, snippet_tokens: int = 512, document_tokens: int = 8192):
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field

    app = FastAPI(title="CALC shared official BrowseComp-Plus BM25")
    io_lock = threading.RLock()
    tokenizer_lock = threading.Lock()
    cache_lock = threading.Lock()
    cache = OrderedDict()
    key_locks = {}

    def cached(key, build):
        # The pinned corpus is immutable. Cache exact rendered results, never
        # summaries, and coalesce identical concurrent requests.
        with cache_lock:
            key_lock = key_locks.setdefault(key, threading.Lock())
        with key_lock:
            with cache_lock:
                if key in cache:
                    cache.move_to_end(key)
                    return cache[key]
            value = build()
            with cache_lock:
                cache[key] = value
                cache.move_to_end(key)
                while len(cache) > 256:
                    cache.popitem(last=False)
            return value

    class SearchRequest(BaseModel):
        query: str = Field(min_length=1, max_length=20000)

    class DocumentRequest(BaseModel):
        docid: str = Field(min_length=1, max_length=1000)

    def truncate(text: str, cap: int):
        with tokenizer_lock:
            ids = tokenizer.encode(text, add_special_tokens=False)
            return (tokenizer.decode(ids[:cap], skip_special_tokens=True) if len(ids) > cap else text,
                    len(ids) > cap)

    def render(raw, cap):
        title, text = split_title(raw)
        text, truncated = truncate(text, cap)
        return title, text, truncated

    @app.get("/health")
    def health():
        return {
            "status": "ok", "retriever": "official BM25Searcher",
            "source_commit": SOURCE_COMMIT, "index_revision": INDEX_REVISION,
            "tokenizer": "Qwen/Qwen3-0.6B", "tokenizer_revision": tokenizer_revision,
            "k": k, "snippet_max_tokens": snippet_tokens,
            "document_max_tokens": document_tokens,
            "render_cache": "exact deterministic LRU, 256 entries",
            "tool_contract": {"search": "POST /retrieve", "get_document": "POST /document"},
            "source_file_sha256": {
                name: hashlib.sha256((source_root / "searcher" / "searchers" / name).read_bytes()).hexdigest()
                for name in ("base.py", "bm25_searcher.py")
            },
        }

    @app.post("/retrieve")
    def retrieve(request: SearchRequest):
        if not request.query.strip():
            raise HTTPException(400, "query must not be blank")
        def search():
            with io_lock:
                candidates = searcher.search(request.query, k)
            results = []
            for hit in candidates:
                title, snippet, _ = cached(("snippet", str(hit["docid"])),
                                           lambda hit=hit: render(hit["text"], snippet_tokens))
                results.append({"docid": str(hit["docid"]), "document": {"title": title, "text": snippet}})
            return {"result": results}
        return cached(("search", request.query), search)

    @app.post("/document")
    def document(request: DocumentRequest):
        def read():
            with io_lock:
                found = searcher.get_document(request.docid)
            if found is None:
                raise HTTPException(404, "document not found")
            title, text, truncated = render(found["text"], document_tokens)
            return {"document": {"docid": str(found["docid"]), "title": title, "text": text},
                    "truncated": truncated}
        return cached(("document", request.docid), read)

    return app


def main():
    import faulthandler
    import signal
    faulthandler.enable()
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("/opt/calc/upstreams/BrowseComp-Plus"))
    parser.add_argument("--index-path", type=Path, default=EXP_ROOT / "bench" / "browsecomp-plus" / "indexes" / "bm25")
    parser.add_argument("--cache-dir", type=Path, default=EXP_ROOT / "cache" / "hf")
    parser.add_argument("--tokenizer-revision", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    os.environ["HF_HOME"] = str(args.cache_dir)
    os.environ["HF_HUB_CACHE"] = str(args.cache_dir / "hub")
    os.environ["HF_XET_CACHE"] = str(args.cache_dir / "xet")
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    import uvicorn
    from transformers import AutoTokenizer
    bm25 = load_official_bm25(args.source_root)
    searcher = bm25(types.SimpleNamespace(index_path=str(args.index_path)))
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-0.6B", revision=args.tokenizer_revision)
    app = create_app(searcher, tokenizer, source_root=args.source_root,
                     tokenizer_revision=args.tokenizer_revision)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
