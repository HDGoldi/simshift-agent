import ast
import pathlib


def test_pattern_imports_nothing_from_simshift():
    for f in pathlib.Path(__file__).parents[1].rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
                assert not any(n.startswith("simshift") for n in names), f
