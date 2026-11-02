"""Extract current implementation for reading; never create another runtime.

Run from any directory with Python 3.11+. The generated .py is a source-reading
snapshot with original methods dedented; use the existing runners to execute CALC.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parents[1]
SECTIONS = {
    'progress.py': ['WorkReport'],
    'triggers.py': ['compile_candidate'],
    'scheduling.py': ['scoped_revision_tool', 'continuation_panel'],
    'adaptive.py': ['AdaptiveRuntime._compile_opportunity', 'AdaptiveRuntime._accept_decision',
                    'AdaptiveRuntime.change', 'AdaptiveRuntime._apply_change', 'AdaptiveRuntime._accept'],
}


def export(destination: Path) -> None:
    blocks = ['# ruff: noqa -- generated source-reading snapshot, not a standalone runtime\n'
              '"""CALC task-progress core: generated READING snapshot, not an execution entrypoint.\n'
              'Methods keep their self argument and depend on the original modules.\n'
              'Source paths, line numbers and SHA256 identify the exact extracted implementation.\n'
              'Regenerate: python scripts/export_collaboration_core.py\n"""',
              'from __future__ import annotations\nfrom dataclasses import dataclass, field']
    for filename, selections in SECTIONS.items():
        relative = Path('src/calc') / filename
        source = (ROOT / relative).read_text(encoding='utf-8')
        tree = ast.parse(source)
        for selector in selections:
            container = tree
            for name in selector.split('.'):
                container = next(node for node in container.body if getattr(node, 'name', None) == name)
            start = min([container.lineno, *[node.lineno for node in getattr(container, 'decorator_list', [])]])
            segment = '\n'.join(source.splitlines()[start - 1:container.end_lineno])
            blocks.append(f'# SOURCE {relative.as_posix()}:{start}  {selector}\n'
                          f'# SHA256 {hashlib.sha256(source.encode()).hexdigest()}\n' + textwrap.dedent(segment))
    result = '\n\n\n'.join(blocks) + '\n'
    compile(result, str(destination), 'exec')  # verify syntax, never execute the snapshot
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(result, encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    export(ROOT / 'docs/excerpts/progress_operator_core.py')
