# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

import ast
from pathlib import Path

import pytest

from patterns.capability_aware_router.examples import document_processing


def test_example_imports_no_domain_package_and_exposes_help() -> None:
    source = Path(document_processing.__file__).read_text(encoding="utf-8")
    imported_roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert "simshift" not in imported_roots
    with pytest.raises(SystemExit) as exit_info:
        document_processing.main(["--help"])
    assert exit_info.value.code == 0
