"""Verify the intentional defect and a fix control only in a disposable copy."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/benchmark"))

import runner  # noqa: E402

scenario = runner.load_scenario("field-notes")
with tempfile.TemporaryDirectory(prefix="field-notes-race-", dir="/tmp") as temp:
    workspace, _, _ = runner.prepare(runner.baseline_archive(scenario["baseline"]), Path(temp))
    shutil.copytree(
        scenario["baseline"] / "frontend/node_modules",
        workspace / "frontend/node_modules",
        symlinks=True,
    )
    shutil.copy2(
        Path(__file__).with_name("reproduce.test.ts"),
        workspace / "frontend/tests/reproduce.test.ts",
    )
    env = dict(os.environ)
    subprocess.run(
        ["npm", "test", "--", "tests/reproduce.test.ts"],
        cwd=workspace / "frontend",
        env=env,
        check=True,
    )
    app = workspace / "frontend/src/app.ts"
    text = app.read_text()
    text = text.replace(
        "        if (current !== revision) return;\n        results.replaceChildren",
        "        results.replaceChildren",
        1,
    ).replace(
        "        summary.textContent =",
        "        if (current !== revision) return;\n        summary.textContent =",
        1,
    )
    app.write_text(text)
    result = subprocess.run(
        ["npm", "test", "--", "tests/reproduce.test.ts"],
        cwd=workspace / "frontend",
        env=env,
        capture_output=True,
    )
    if result.returncode == 0:
        raise RuntimeError("Defect reproduction also passed on fixed copy")
    print(
        "Known-fix control: defect assertion correctly fails after moving the guard "
        "(disposable copy only)."
    )
