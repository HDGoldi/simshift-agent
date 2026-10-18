# Copyright 2026 SIMShift contributors
# SPDX-License-Identifier: Apache-2.0

"""Check Apache-2.0 headers on project-owned Python and shell files."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPES = (ROOT / "src", ROOT / "patterns", ROOT / "tests", ROOT / "scripts")
COPYRIGHT = "Copyright 2026 SIMShift contributors"
SPDX = "SPDX-License-Identifier: Apache-2.0"


def main() -> int:
    failures: list[str] = []
    checked = 0
    for scope in SCOPES:
        for path in sorted(scope.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".sh"}:
                continue
            checked += 1
            first_lines = path.read_text(encoding="utf-8").splitlines()[:4]
            if not any(COPYRIGHT in line for line in first_lines) or not any(
                SPDX in line for line in first_lines
            ):
                failures.append(str(path.relative_to(ROOT)))
    if failures:
        print("missing license header: " + ", ".join(failures))
        return 1
    print(f"license headers valid: {checked} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
