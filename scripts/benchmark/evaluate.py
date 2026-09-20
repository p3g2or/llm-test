#!/usr/bin/env python3
"""Review saved evidence using Codex subscription auth or explicit OpenRouter."""

import argparse
import fcntl
import hashlib
import io
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import runner

VERSION = 3
HEARTBEAT_SECONDS = 15
PRIMARY_EVIDENCE = {
    "task.md",
    "response.txt",
    "diff.patch",
    "metrics.json",
    "check.log",
    "evaluation-guidance.md",
    "source-provenance.txt",
}
FIELDS = (
    "findings_summary",
    "observed_correctness",
    "test_quality_coverage",
    "scope_discipline",
    "independently_discovered_issues",
    "known_bug_discovery",
)
PROMPT_DIR = Path(__file__).resolve().parents[2] / "scenarios/field-notes/evaluation"
SYSTEM = (PROMPT_DIR / "assessment.md").read_text(encoding="utf-8")
SYNTHESIS_SYSTEM = (PROMPT_DIR / "synthesis.md").read_text(encoding="utf-8")


def progress(message):
    print(f"[evaluate] {message}", file=sys.stderr, flush=True)


def run_reference(run):
    """Persist checkout-independent references, including legacy absolute paths."""
    path = Path(run)
    if path.is_absolute():
        if path.is_relative_to(runner.ROOT):
            return path.relative_to(runner.ROOT).as_posix()
        if "results" in path.parts:
            return Path(*path.parts[path.parts.index("results") :]).as_posix()
        return Path(os.path.relpath(path, runner.ROOT)).as_posix()
    return path.as_posix()


def benchmark_inputs(run):
    metadata = json.loads((run / "run.json").read_text())
    return {
        "prompt": metadata.get("prompt"),
        "prompt_version": metadata.get("prompt_version"),
        "evaluation_guidance": metadata.get("evaluation_guidance"),
        "baseline_sha256": metadata.get("archive_sha256"),
        "source_sha256": metadata.get("source_sha256", {}),
    }


@contextmanager
def waiting(label):
    """Report liveness without exposing model output or claiming model progress."""
    started = time.monotonic()
    stopped = threading.Event()

    def heartbeat():
        while not stopped.wait(HEARTBEAT_SECONDS):
            progress(f"{label}: still waiting ({time.monotonic() - started:.0f}s elapsed)")

    progress(f"{label}: started")
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


ASSESSMENT_SCHEMA = object_schema(
    {
        **{field: {"type": "string"} for field in FIELDS},
        "evidence_citations": {"type": "array", "items": {"type": "string"}},
    }
)
LEGACY_SYNTHESIS_SCHEMA = object_schema(
    {name: {"type": "string"} for name in ("short_decision", "tradeoffs")}
)
SYNTHESIS_SCHEMA = object_schema(
    {
        "short_decision": {"type": "string"},
        "quality_scores": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0, "maximum": 100},
        },
    }
)
METRIC_FIELDS = (
    "model",
    "requested_model_id",
    "actual_served_model_id",
    "actual_served_models",
    "actual_providers",
    "status",
    "timeout",
    "validation",
    "coding_duration_seconds",
)


def finished(path):
    metrics = json.loads((path / "metrics.json").read_text())
    return bool(metrics.get("ended_at") and metrics.get("status") != "prepared")


def latest_runs(models):
    runs = []
    for model in sorted(models):
        if not (model / "runs").is_dir() and not (model / "latest").is_symlink():
            continue
        latest = model / "latest"
        if not (latest / "metrics.json").is_file() or not (latest / "run.json").is_file():
            progress(f"Skipping missing or incomplete latest attempt: {latest}")
            continue
        try:
            metadata = json.loads((latest / "run.json").read_text())
            ready = finished(latest) and isinstance(metadata, dict) and not metadata.get("dry_run")
        except (OSError, ValueError, AttributeError):
            ready = False
        if not ready:
            progress(f"Skipping unfinished, unreadable or dry-run latest attempt: {latest}")
            continue
        runs.append(latest.resolve())
    return runs


def discover(target, parent):
    if target == "all":
        candidates = latest_runs(parent.glob("*/*/*"))
    else:
        path = Path(target).expanduser()
        if not path.exists():
            path = parent / target
        candidates = [path.resolve()]
    runs = []
    for path in candidates:
        if not (path / "metrics.json").is_file():
            raise ValueError(f"Not a saved run: {path}")
        metadata = json.loads((path / "run.json").read_text())
        if metadata.get("dry_run"):
            raise ValueError(f"Run is marked dry-run: {path}")
        if finished(path):
            runs.append(path)
    if not runs:
        raise ValueError("No finished non-dry benchmark runs found")
    return runs


def discover_comparison(target, parent):
    """Select only each model's latest attempt, never an older successful run."""
    path = Path(target).expanduser()
    if not path.exists():
        path = parent / target
    path = path.resolve()
    runs = latest_runs(path.glob("*"))
    if not runs:
        raise ValueError("Comparison target must be a scenario/task with finished runs")
    inputs = [source_artifacts(run)[0] for run in runs]
    for name, label in (
        ("task.md", "task prompts"),
        ("baseline.tar", "baselines"),
        ("evaluation-guidance.md", "evaluation guidance"),
    ):
        if len({digest(raw.get(name, b"")) for raw in inputs}) != 1:
            progress(f"Warning: comparing different {label}")
    return runs


def artifact_path(run, name):
    local = run / name
    if name not in {"task.md", "evaluation-guidance.md", "baseline.tar"} or local.is_file():
        return local
    run = run.resolve()
    if run.parent.name == "runs":
        task = run.parents[2]
        return (task.parent if name == "baseline.tar" else task) / name
    return run.parent / name


def source_artifacts(run):
    """Use saved inputs first; label missing historical sources rather than blocking."""
    metadata = json.loads((run / "run.json").read_text())
    raw, provenance = {}, []
    for name in ("task.md", "evaluation-guidance.md", "baseline.tar"):
        path = artifact_path(run, name)
        if path.is_file():
            raw[name] = path.read_bytes()
    for name, field in (("task.md", "prompt"), ("evaluation-guidance.md", "evaluation_guidance")):
        if metadata.get(field) is not None:
            raw[name] = metadata[field].encode("utf-8")
    missing = {"task.md", "evaluation-guidance.md", "baseline.tar"} - raw.keys()
    if missing:
        try:
            scenario = runner.load_scenario(metadata["scenario"], task=metadata["task_name"])
            fallback = {
                "task.md": scenario["prompt"].encode("utf-8"),
                "evaluation-guidance.md": scenario["evaluation_guidance"].encode("utf-8"),
            }
            if "baseline.tar" in missing:
                fallback["baseline.tar"] = runner.baseline_archive(scenario["baseline"])
            raw.update({name: fallback[name] for name in missing})
        except (OSError, ValueError, KeyError) as error:
            progress(f"Warning: historical source unavailable for {run}: {error}")
            raw.update({name: b"" if name == "baseline.tar" else b"[MISSING]" for name in missing})
    expected = dict(metadata.get("source_sha256", {}))
    if metadata.get("archive_sha256"):
        expected["baseline.tar"] = metadata["archive_sha256"]
    for name, value in sorted(raw.items()):
        matches = name in expected and digest(value) == expected[name]
        origin = "current scenario reference" if name in missing else "saved input"
        verification = (
            "verified against saved SHA-256" if matches else "historical identity unverified"
        )
        if name in expected and not matches:
            verification = (
                "differs from saved SHA-256; CURRENT REFERENCE ONLY"
                if name in missing
                else "differs from saved SHA-256"
            )
            progress(f"Warning: {run.name}/{name}: {verification}")
        provenance.append(f"{name}: {origin}; {verification}.")
    return raw, "\n".join(provenance) + "\n"


def evidence(run, inputs=None):
    names = [
        "run.json",
        "task.md",
        "response.txt",
        "diff.patch",
        "metrics.json",
        "check.log",
        "evaluation-guidance.md",
    ]
    raw, provenance = source_artifacts(run) if inputs is None else inputs
    data = {
        name: raw[name].decode("utf-8")
        if name in raw
        else (run / name).read_text()
        if (run / name).is_file()
        else "[MISSING]"
        for name in names
    }
    data["source-provenance.txt"] = provenance
    for name in ("transcript.jsonl", "api-calls.json", "opencode.log"):
        data[name] = (run / name).read_text() if (run / name).is_file() else "[MISSING]"
    sources = {}
    # Read members, never extract archive paths, symlinks or executable files.
    if not raw["baseline.tar"]:
        data["baseline_source"] = {"UNAVAILABLE.txt": "Historical baseline source unavailable."}
        return data
    with tarfile.open(fileobj=io.BytesIO(raw["baseline.tar"])) as archive:
        for member in archive.getmembers():
            if member.isfile():
                raw = archive.extractfile(member).read()
                try:
                    sources[member.name] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    sources[member.name] = f"[BINARY: {len(raw)} bytes; sha256={digest(raw)}]"
    data["baseline_source"] = sources
    return data


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def numbered(text):
    # split on LF only: JSONL citations refer to physical lines, not Unicode separators.
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1)) + "\n"


def prepare_evidence(run, workspace):
    inputs = source_artifacts(run)
    data = evidence(run, inputs)
    manifest = {"run": run_reference(run), "files": [], "missing": []}
    for name, content in data.items():
        entries = content.items() if name == "baseline_source" else [(name, content)]
        for source, text in entries:
            label = f"baseline.tar:{source}" if name == "baseline_source" else source
            filename = f"evidence-{len(manifest['files']):04d}.txt"
            (workspace / filename).write_text(numbered(text), encoding="utf-8")
            manifest["files"].append(
                {
                    "file": filename,
                    "source": label,
                    "bytes": len(text.encode("utf-8")),
                    "lines": text.count("\n") + int(bool(text) and not text.endswith("\n")),
                    "priority": "primary" if label in PRIMARY_EVIDENCE else "on-demand",
                }
            )
            if text == "[MISSING]":
                manifest["missing"].append(label)
    hashes = {name: digest(raw) for name, raw in inputs[0].items()}
    for name in data:
        if name not in hashes and (run / name).is_file():
            hashes[name] = digest((run / name).read_bytes())
    hashes["source-provenance.txt"] = digest(inputs[1].encode("utf-8"))
    manifest["sha256"] = hashes
    (workspace / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return data, manifest


def codex_environment():
    # Keep CODEX_HOME for existing subscription login; never propagate API routing/auth.
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("OPENAI_", "OPENROUTER_", "AZURE_OPENAI_"))
        and key.upper()
        not in {
            "CODEX_API_KEY",
            "CODEX_BASE_URL",
            "CODEX_ACCESS_TOKEN",
            "CODEX_AUTH_JSON",
            "CODEX_MODEL",
            "CHATGPT_BASE_URL",
        }
    }


def run_process(command, cwd, env, timeout, prompt=None):
    """Kill the entire process group on timeout; never accept partial final text."""
    with subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(prompt, timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise RuntimeError(
                f"Evaluator interrupted or exceeded {timeout}s; "
                "earlier saved assessments are retained"
            ) from None
        if process.returncode:
            # Report recognizable causes without echoing credentials or evidence from CLI output.
            diagnostic = (stderr + "\n" + stdout).lower()
            hints = []
            for markers, hint in (
                (("reasoning_effort", "reasoning effort"), "check model reasoning effort support"),
                (("usage limit", "quota", "rate limit"), "Codex reports a usage or rate limit"),
                (("unauthorized", "authentication", "not logged in"), "check Codex login"),
                (("invalid schema", "invalid_json_schema"), "Codex rejected the output schema"),
                (("connection", "stream disconnected"), "Codex reports a connection failure"),
            ):
                if any(marker in diagnostic for marker in markers):
                    hints.append(hint)
            detail = "; " + "; ".join(hints) if hints else ""
            raise RuntimeError(
                f"Codex exited with status {process.returncode}{detail}; "
                "earlier saved assessments are retained"
            )
        return stdout, stderr


def codex_preflight(timeout=30):
    progress("Checking Codex ChatGPT login (up to 30s)")
    with tempfile.TemporaryDirectory(prefix="benchmark-login-") as temp:
        stdout, stderr = run_process(
            [
                "codex",
                "-c",
                'forced_login_method="chatgpt"',
                "-c",
                'model_provider="openai"',
                "login",
                "status",
            ],
            temp,
            codex_environment(),
            min(timeout, 30),
        )
    status = (stdout + stderr).lower()
    if "logged in using chatgpt" not in status or "api key" in status or "api_key" in status:
        raise ValueError(
            "Codex requires ChatGPT subscription login; run codex login (not --with-api-key)"
        )


def codex_command(workspace, output, schema, config, instructions=SYSTEM):
    command = [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--json",
        "--output-last-message",
        str(output),
        "--output-schema",
        str(schema),
        "-C",
        str(workspace),
    ]
    overrides = [
        'forced_login_method="chatgpt"',
        'model_provider="openai"',
        'model_reasoning_effort="low"',
        'approval_policy="never"',
        'web_search="disabled"',
        "project_doc_max_bytes=0",
        "mcp_servers={}",
        "allow_login_shell=false",
        'shell_environment_policy.inherit="none"',
        "skills.include_instructions=false",
        "skills.bundled.enabled=false",
        "memories.use_memories=false",
        "memories.generate_memories=false",
        "features.skip_host_skill_discovery=true",
        "features.apps=false",
        "features.plugins=false",
        "features.hooks=false",
        "features.multi_agent=false",
        "features.multi_agent_v2=false",
        "features.browser_use=false",
        "features.computer_use=false",
        "features.image_generation=false",
        "features.js_repl=false",
        "features.shell_snapshot=false",
        "developer_instructions=" + json.dumps(instructions),
    ]
    for value in overrides:
        command += ["-c", value]
    if config.get("model"):
        command += ["--model", config["model"]]
    return command + ["-"]


def validate_schema(value, schema):
    kind = schema["type"]
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
    }[kind]
    if not valid:
        raise ValueError(f"Evaluator returned invalid {kind}")
    if kind == "object":
        if set(value) != set(schema["properties"]):
            raise ValueError("Evaluator returned incomplete or unexpected fields")
        for key, child in schema["properties"].items():
            validate_schema(value[key], child)
    elif kind == "array":
        for child in value:
            validate_schema(child, schema["items"])

    elif kind == "integer" and not schema["minimum"] <= value <= schema["maximum"]:
        raise ValueError("Evaluator returned a quality score outside 0-100")
    elif kind == "string" and not value.strip():
        raise ValueError("Evaluator returned an empty assessment field")


def openrouter_evidence(workspace):
    """The tool-free fallback gets a bounded primary packet, not the full archive."""
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        return {p.name: p.read_text() for p in sorted(workspace.glob("*")) if p.is_file()}
    manifest = json.loads(manifest_path.read_text())
    files = {"manifest.json": manifest_path.read_text()}
    for item in manifest["files"]:
        if item["priority"] == "primary":
            text = (workspace / item["file"]).read_text()
            files[item["file"]] = text[:16000]
            if len(text) > 16000:
                files[item["file"]] += "\n[TRUNCATED: remaining evidence not supplied]"
    files["review-scope.txt"] = (
        "Tool-free review: only primary evidence excerpts are supplied. On-demand files "
        "listed in the manifest are unavailable, not reviewed. Do not claim independent "
        "source or transcript verification. Disclose these limits and unsupported claims."
    )
    return files


def request_assessment(workspace, config, schema, prompt, key=None):
    instructions = SYNTHESIS_SYSTEM if schema == SYNTHESIS_SCHEMA else SYSTEM
    if config.get("backend", "openrouter") == "codex":
        with tempfile.TemporaryDirectory(prefix="benchmark-response-") as temp:
            output = Path(temp) / "final.json"
            schema_path = Path(temp) / "schema.json"
            schema_path.write_text(json.dumps(schema))
            command = codex_command(workspace, output, schema_path, config, instructions)
            stdout, _ = run_process(
                command, workspace, codex_environment(), config["timeout"], prompt
            )
            events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            if not any(e.get("type") == "turn.completed" for e in events) or any(
                e.get("type") in {"turn.failed", "error"} for e in events
            ):
                raise ValueError("Codex did not finish successfully; refusing partial output")
            findings = json.loads(output.read_text())
            usage = next(
                (e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"),
                None,
            )
            provenance = {"served_model": None, "usage": usage}
    else:
        files = openrouter_evidence(workspace)
        payload = {
            "model": config["model"],
            "max_tokens": config.get("max_tokens", 8192),
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": instructions + "\nNo tools are available.\n" + prompt,
                },
                {"role": "user", "content": json.dumps({"schema": schema, "files": files})},
            ],
        }
        request = urllib.request.Request(
            runner.API + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
            body = json.load(response)
        choice = body["choices"][0]
        if choice.get("finish_reason") not in (None, "stop"):
            raise ValueError("OpenRouter response incomplete; refusing partial output")
        findings = json.loads(choice["message"]["content"])
        provenance = {"served_model": body.get("model"), "usage": body.get("usage")}
    return findings, provenance


def nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def project_saved(value, schema):
    """Drop obsolete saved fields without rewriting retained judgments."""
    if isinstance(value, dict):
        value = {name: value[name] for name in schema["properties"] if name in value}
    validate_schema(value, schema)
    return value


def cost_metadata(metrics, calls):
    cost = metrics.get("actual_cost_usd")
    lower = sum(
        c.get("usage", {}).get("cost", 0)
        for c in calls
        if isinstance(c, dict)
        and isinstance(c.get("usage"), dict)
        and nonnegative(c["usage"].get("cost"))
    )
    complete = nonnegative(cost)
    return {
        "cost_complete": complete,
        "cost_usd": cost if complete else None,
        "cost_lower_bound_usd": lower,
    }


def assess(run, config, key=None):
    progress(f"Preparing evidence: {run}")
    with tempfile.TemporaryDirectory(prefix="benchmark-evidence-") as temp:
        workspace = Path(temp)
        data, manifest = prepare_evidence(run, workspace)
        prompt = SYSTEM
        label = (
            f"Assessment {run.name} ({config.get('backend', 'openrouter')}, "
            f"timeout {config['timeout']}s)"
        )
        with waiting(label):
            findings, provenance = request_assessment(
                workspace, config, ASSESSMENT_SCHEMA, prompt, key
            )
        progress(f"Assessment {run.name}: response received; validating")
    validate_schema(findings, ASSESSMENT_SCHEMA)
    result = {
        "schema_version": VERSION,
        "backend": config.get("backend", "openrouter"),
        "evaluator_model": config.get("model") or "codex-default",
        "evaluated_at": runner.now(),
        "benchmark_run": run_reference(run),
        "benchmark_inputs": benchmark_inputs(run),
        "provenance": manifest,
        "findings": findings,
        **provenance,
    }
    calls = [] if data["api-calls.json"] == "[MISSING]" else json.loads(data["api-calls.json"])
    if not isinstance(calls, list):
        raise ValueError("api-calls.json must contain an array")
    metrics = json.loads(data["metrics.json"])
    result["metrics"] = {name: metrics[name] for name in METRIC_FIELDS if name in metrics}
    result.update(cost_metadata(metrics, calls))
    return result


def save_report(directory, stem, result, markdown, key=None):
    """Preserve previous files, then publish the new report."""
    directory.mkdir(parents=True, exist_ok=True)
    backup_reports(directory, stem)
    with tempfile.TemporaryDirectory(prefix=".evaluation-", dir=directory) as temp:
        for suffix, content in (("json", result), ("md", markdown)):
            runner.save(Path(temp) / suffix, content, key)
        for suffix in ("json", "md"):
            os.replace(Path(temp) / suffix, directory / f"{stem}.{suffix}")


def assessment_markdown(result):
    return f"## Run: {result['benchmark_run']}\n\n{comparison_review(result['findings'])}"


def evaluate(run, config, key=None):
    """Legacy callers passing a key/config without backend retain OpenRouter behavior."""
    config = {**config, "backend": config.get("backend", "openrouter" if key else "codex")}
    if config["backend"] == "codex":
        codex_preflight(config["timeout"])
    result = assess(run, config, key)
    save_report(run, "evaluation", result, "# AI evaluation\n\n" + assessment_markdown(result), key)
    progress(f"Saved evaluation: {run / 'evaluation.md'}")
    return result


def comparison_review(findings):
    return " ".join(findings[field] for field in FIELDS)


def validate_quality_scores(synthesis, runs):
    validate_schema(synthesis["quality_scores"], SYNTHESIS_SCHEMA["properties"]["quality_scores"])
    if len(synthesis["quality_scores"]) != len(runs):
        raise ValueError("Expected one quality score per assessment")


def comparison_markdown(result):
    synthesis = result.get("synthesis") or {}
    scores = synthesis.get("quality_scores")
    if scores is not None:
        validate_quality_scores(synthesis, result["runs"])
    runs = sorted(
        enumerate(result["runs"]), key=lambda item: item[1]["metrics"]["model"].casefold()
    )
    parts = ["# Benchmark comparison"]
    if synthesis.get("short_decision"):
        parts.append("## Summary\n\n" + synthesis["short_decision"])
    parts.append("| Model | Quality (0–100) | Time(s) | USD |\n|---|---:|---:|---:|")
    for index, run in runs:
        metrics = run["metrics"]
        alias = metrics["model"].replace("|", "\\|").replace("\n", " ")
        seconds = metrics.get("coding_duration_seconds")
        coding = f"{seconds:.0f}" if seconds is not None else "unknown"
        cost = (
            f"${run['cost_usd']:.4f}"
            if run["cost_complete"]
            else f">=${run['cost_lower_bound_usd']:.4f} (incomplete)"
        )
        quality = str(scores[index]) if scores is not None else "not scored"
        parts[-1] += "\n| " + " | ".join([alias, quality, coding, cost]) + " |"
    for _, run in runs:
        alias = " ".join(run["metrics"]["model"].split())
        parts.append(f"## {alias}\n\n{comparison_review(run['findings'])}")
    return "\n\n".join(parts) + "\n"


def save_comparison_file(path, state, key=None):
    if path.is_file():
        try:
            if (
                json.loads(path.read_text()) if isinstance(state, dict) else path.read_text()
            ) == state:
                return
        except ValueError:
            pass
    with tempfile.TemporaryDirectory(prefix=".comparison-", dir=path.parent) as temp:
        staged = Path(temp) / "state.json"
        runner.save(staged, state, key)
        os.replace(staged, path)


def comparison_identity(runs, config):
    return {
        "config": config,
        "runs": [
            {
                "path": run_reference(run),
                "evidence_sha256": digest(json.dumps(evidence(run), sort_keys=True).encode()),
            }
            for run in runs
        ],
    }


def compare(runs, config, output_dir, key=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / ".checkpoint.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f"Comparison is already running: {output_dir}") from None
        return compare_checkpointed(runs, config, output_dir, key)


def compact_assessment(result):
    # Keep documented findings and input metadata; raw evidence stays local.
    omitted = {
        "events",
        "provenance",
        "scores",
        "total",
        "rank",
        "handoff_cap",
        "completed_handoff",
    }
    compact = {name: value for name, value in result.items() if name not in omitted}
    if "benchmark_run" in compact:
        compact["benchmark_run"] = run_reference(compact["benchmark_run"])
    if "findings" in compact:
        compact["findings"] = project_saved(compact["findings"], ASSESSMENT_SCHEMA)
    if "metrics" in compact:
        compact["metrics"] = {
            name: compact["metrics"][name] for name in METRIC_FIELDS if name in compact["metrics"]
        }
    return compact


def load_comparison(output_dir, identity):
    """Reuse valid assessments individually; changes never invalidate unrelated work."""
    path = output_dir / "comparison.json"
    legacy = output_dir / "checkpoint.json"
    state = {}
    try:
        source = path if path.exists() else legacy
        if source.exists():
            state = json.loads(source.read_text())
            if not isinstance(state, dict):
                state = {}
            if "identity" not in state and legacy.exists():
                state["identity"] = json.loads(legacy.read_text()).get("identity", {})
    except (ValueError, TypeError):
        progress(
            "Warning: unreadable saved state; previous files will be backed up before rebuilding"
        )
    saved_identity = state.get("identity") or {}
    if not isinstance(saved_identity, dict):
        saved_identity = {}
    saved_identity = {
        **saved_identity,
        "runs": [
            {**item, "path": run_reference(item["path"])}
            for item in saved_identity.get("runs", [])
            if isinstance(item, dict) and "path" in item
        ],
    }
    identity = {
        **identity,
        "runs": [{**item, "path": run_reference(item["path"])} for item in identity["runs"]],
    }
    previous = {
        item["path"]: item
        for item in saved_identity.get("runs", [])
        if isinstance(item, dict) and "path" in item
    }
    # A public checkout has assessments but no private results. Retain these
    # unless a local model directory explicitly selects a replacement attempt.
    selected_models = {
        Path(item["path"]).parents[1]
        for item in identity["runs"]
        if len(Path(item["path"]).parents) > 1
    }
    published = []
    for item in saved_identity["runs"]:
        reference = Path(item["path"])
        if len(reference.parents) < 2:
            continue
        model = reference.parents[1]
        if model not in selected_models and not (runner.ROOT / model).exists():
            published.append(item)
    if published:
        progress(
            f"Reusing {len(published)} published assessments; "
            "original evidence is not available locally"
        )
        identity = {
            **identity,
            "runs": sorted(
                [*identity["runs"], *published], key=lambda item: Path(item["path"]).parts
            )
            if identity["runs"]
            else published,
        }
    selected = [item["path"] for item in identity["runs"]]
    wanted = {item["path"]: item for item in identity["runs"]}
    retained = {}
    saved_runs = state.get("runs", state.get("results", []))
    for result in saved_runs if isinstance(saved_runs, list) else []:
        try:
            name = run_reference(result["benchmark_run"])
            if name not in wanted:
                continue
            if previous.get(name) != wanted[name]:
                progress(f"Warning: changed evidence; reassessing {name}")
                continue
            project_saved(result["findings"], ASSESSMENT_SCHEMA)
            if not isinstance(result.get("metrics"), dict) or "model" not in result["metrics"]:
                raise ValueError("Missing assessment metrics")
            retained[name] = compact_assessment(result)
        except (KeyError, TypeError, ValueError):
            progress("Warning: incomplete saved assessment; rebuilding only that assessment")
    assessments = [retained[name] for name in selected if name in retained]
    baseline_hashes = {
        result.get("benchmark_inputs", {}).get("baseline_sha256") for result in assessments
    } - {None}
    if len(baseline_hashes) > 1:
        progress(
            "Warning: saved assessments used different baseline hashes; "
            "comparison remains available"
        )
    same_inputs = saved_identity.get("runs") == identity["runs"]
    synthesis = state.get("synthesis")
    if isinstance(synthesis, dict) and "findings" in synthesis:
        state["synthesis_provenance"] = synthesis.get("provenance")
        synthesis = synthesis["findings"]
    if not same_inputs or len(assessments) != len(selected):
        synthesis = None
    if synthesis is not None:
        try:
            schema = SYNTHESIS_SCHEMA if "quality_scores" in synthesis else LEGACY_SYNTHESIS_SCHEMA
            if "quality_scores" in synthesis and "tradeoffs" in synthesis:
                schema = object_schema(
                    {**SYNTHESIS_SCHEMA["properties"], "tradeoffs": {"type": "string"}}
                )
            synthesis = project_saved(synthesis, schema)
            if "quality_scores" in synthesis:
                validate_quality_scores(synthesis, assessments)
        except (KeyError, TypeError, ValueError):
            progress("Warning: incomplete saved synthesis; rebuilding summary")
            synthesis = None
    if saved_identity.get("config") and saved_identity["config"] != identity["config"]:
        progress(
            "Warning: evaluator settings changed; saved assessments keep their original provenance"
        )
    if synthesis is not None:
        identity = {**identity, "config": saved_identity.get("config", identity["config"])}
    result = {
        "state_version": 1,
        "schema_version": VERSION,
        "status": "completed" if synthesis is not None else "assessing",
        "identity": identity,
        "config": state.get("config", identity["config"])
        if synthesis is not None
        else identity["config"],
        "runs": assessments,
        "synthesis": synthesis,
        "synthesis_provenance": compact_assessment(state.get("synthesis_provenance") or {})
        if synthesis is not None
        else None,
    }
    if synthesis is not None:
        for field in ("evaluated_at", "synthesis_policy", "quality_scoring_provenance"):
            if field in state:
                result[field] = state[field]
    return result


def backup_reports(directory, stem="comparison"):
    files = [directory / f"{stem}.{suffix}" for suffix in ("json", "md")]
    if stem == "comparison":
        files.append(directory / "checkpoint.json")
    files = [path for path in files if path.is_file()]
    if files:
        parent = directory / "history"
        parent.mkdir(exist_ok=True)
        backup = Path(
            tempfile.mkdtemp(
                prefix=runner.dt.datetime.now(runner.dt.UTC).strftime("%Y%m%dT%H%M%SZ-"), dir=parent
            )
        )
        for path in files:
            shutil.copy2(path, backup / path.name)
        progress(f"Previous reports saved: {backup}")


def compare_checkpointed(runs, config, output_dir, key=None):
    path = output_dir / "comparison.json"
    progress(f"Saved progress: {path}; repeat the same task command to resume")
    state = load_comparison(output_dir, comparison_identity(runs, config))
    if state["synthesis"] is None:
        backup_reports(output_dir)
    save_comparison_file(path, state, key)
    if state["synthesis"] is None:
        (output_dir / "comparison.md").unlink(missing_ok=True)
    # Remove the redundant legacy file only after its replacement is safely published.
    (output_dir / "checkpoint.json").unlink(missing_ok=True)
    selected = [item["path"] for item in state["identity"]["runs"]]
    remaining = len(selected) - len(state["runs"]) + int(state["synthesis"] is None)
    progress(f"Reusing {len(state['runs'])} assessments; {remaining} model sessions remaining")
    if remaining and config["backend"] == "codex":
        codex_preflight(config["timeout"])
    by_path = {result["benchmark_run"]: result for result in state["runs"]}
    for index, run in enumerate(runs):
        if run_reference(run) in by_path:
            continue
        progress(f"Run {index + 1}/{len(runs)}")
        try:
            by_path[run_reference(run)] = compact_assessment(assess(run, config, key))
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            progress(f"Assessment failed for {run}: {error}; continuing with other runs")
            continue
        state["runs"] = [by_path[item] for item in selected if item in by_path]
        save_comparison_file(path, state, key)
    if len(state["runs"]) != len(selected):
        raise RuntimeError(
            "Some assessments are incomplete; completed work is saved. "
            "Repeat the command to resume."
        )
    if state["synthesis"] is None:
        state["status"] = "synthesizing"
        save_comparison_file(path, state, key)
        with tempfile.TemporaryDirectory(prefix="benchmark-synthesis-") as temp:
            workspace = Path(temp)
            for index, result in enumerate(state["runs"]):
                summary = {
                    "model": result["metrics"]["model"],
                    "metrics": result["metrics"],
                    "findings": result["findings"],
                    **{
                        name: result[name]
                        for name in ("cost_complete", "cost_usd", "cost_lower_bound_usd")
                    },
                }
                (workspace / f"assessment-{index:04d}.json").write_text(
                    json.dumps(summary, indent=2)
                )
            with waiting(f"Comparison synthesis (timeout {config['timeout']}s)"):
                synthesis, provenance = request_assessment(
                    workspace, config, SYNTHESIS_SCHEMA, SYNTHESIS_SYSTEM, key
                )
            validate_schema(synthesis, SYNTHESIS_SCHEMA)
            validate_quality_scores(synthesis, state["runs"])
            state["synthesis"] = synthesis
            state["synthesis_provenance"] = compact_assessment(provenance)
            state["synthesis_policy"] = "holistic-quality-v1"
    state["status"] = "completed"
    state.setdefault("evaluated_at", runner.now())
    save_comparison_file(path, state, key)
    save_comparison_file(output_dir / "comparison.md", comparison_markdown(state), key)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", help="scenario/task directory or all (task summaries only)")
    parser.add_argument("--backend", choices=("codex", "openrouter"), default="codex")
    parser.add_argument(
        "--model", help="backend model ID; Codex uses its built-in default if omitted"
    )
    parser.add_argument("--timeout", type=float, help="seconds per assessment or synthesis")

    parser.add_argument("--config", type=Path, default=runner.ROOT / "config/evaluator.toml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="prepare and inspect evidence; no auth or model calls",
    )
    args = parser.parse_args(argv)

    config = {"backend": args.backend, "model": None, "timeout": 900}
    if args.backend == "codex":
        config["reasoning_effort"] = "low"
    if args.backend == "openrouter":
        with args.config.open("rb") as file:
            config.update(tomllib.load(file))
        config["backend"] = "openrouter"
    if args.model:
        config["model"] = args.model
    if args.timeout is not None:
        config["timeout"] = args.timeout
    if not nonnegative(config["timeout"]) or config["timeout"] == 0:
        parser.error("--timeout must be finite and positive")
    parent = runner.ROOT / "results"
    if args.run == "all":
        targets = sorted(
            {run.parents[2] for run in latest_runs(parent.glob("*/*/*"))}
            | {
                parent / path.parent.parent.name / path.parent.name
                for path in (runner.ROOT / "evaluations").glob("*/*/comparison.json")
            }
        )
        if not targets:
            raise ValueError("No finished runs or published comparisons found")
    else:
        target = Path(args.run).expanduser()
        if not target.exists():
            target = parent / args.run
        if (target / "metrics.json").is_file():
            raise ValueError("Select a scenario/task directory, not an individual run")
        targets = [target.resolve()]
    plans = []
    sessions = 0
    for target in targets:
        output = parent.parent / "evaluations" / target.parent.name / target.name
        if not any(target.glob("*")) and (output / "comparison.json").is_file():
            runs = []
        else:
            runs = discover_comparison(str(target), parent)

        state = load_comparison(output, comparison_identity(runs, config))
        missing = len(state["identity"]["runs"]) - len(state["runs"])
        synthesis = int(state["synthesis"] is None)
        sessions += missing + synthesis
        progress(
            f"Comparison: {len(runs)} runs; destination={output}; "
            f"reusing {len(state['runs'])} assessments; "
            f"{missing} assessments + {synthesis} synthesis"
        )
        assessed = {result["benchmark_run"] for result in state["runs"]}
        for run in runs:
            if run_reference(run) not in assessed:
                progress(f"Needs assessment: {run}")
        plans.append((runs, output))
        if args.dry_run:
            for run in runs:
                with tempfile.TemporaryDirectory(prefix="benchmark-inspect-") as temp:
                    _, manifest = prepare_evidence(run, Path(temp))
                    print(
                        f"{run}: {len(manifest['files'])} evidence files; "
                        f"missing={manifest['missing']}; backend={args.backend}; "
                        f"model={config['model'] or 'codex-default'}"
                    )
            print(
                f"Comparison: {len(runs)} runs; destination={output}; "
                f"{missing} assessments + {synthesis} synthesis (not called)"
            )
    if args.dry_run:
        return 0
    if sessions:
        if not sys.stdin.isatty():
            progress(
                "Cancelled: model calls require interactive confirmation; use --dry-run to inspect"
            )
            return 1
        try:
            confirmed = input("Proceed with this evaluation plan? [y/N] ").strip().lower()
        except (EOFError, OSError, KeyboardInterrupt):
            confirmed = ""
        if confirmed not in {"y", "yes"}:
            progress("Cancelled; no evaluation was saved or called")
            return 1
    failed = False
    for runs, output in plans:
        progress(
            f"Task comparison: {len(runs)} runs; "
            f"backend={args.backend}; model={config['model'] or 'codex-default'}; "
            f"timeout={config['timeout']}s per session"
        )
        key = runner.credential() if args.backend == "openrouter" else None
        try:
            compare(runs, config, output, key)
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            progress(f"Evaluation incomplete for {output}: {error}")
            failed = True
            continue
        print(f"Saved task summary: {output / 'comparison.md'}")
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError, tarfile.TarError) as error:
        print(f"Evaluation failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
