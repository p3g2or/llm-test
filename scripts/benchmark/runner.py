#!/usr/bin/env python3
"""Sequential OpenCode runner. No third-party Python dependencies."""

import argparse
import copy
import datetime as dt
import fnmatch
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.18.30"
TIMEOUT = 900
with (ROOT / "config/models.toml").open("rb") as file:
    config = tomllib.load(file)
MODELS = config["models"]
PROVIDERS = config.get("providers", {})
API = "https://openrouter.ai/api/v1"


def slug(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
        raise ValueError(f"Invalid path name: {value}")
    return value


def prompt_version(scenario, task, prompt):
    path = ROOT / "scenarios" / slug(scenario) / "scenario.toml"
    if not path.is_file():
        return None
    with path.open("rb") as file:
        versions = tomllib.load(file).get("prompt_versions", {}).get(task, {})
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    matches = [version for version, value in versions.items() if value == digest]
    return matches[0] if matches else None


def load_scenario(name="field-notes", task=None):
    directory = ROOT / "scenarios" / slug(name)
    with (directory / "scenario.toml").open("rb") as file:
        config = tomllib.load(file)
    baseline = (directory / config["baseline"]).resolve()
    if not baseline.is_relative_to(directory.resolve()) or not baseline.is_dir():
        raise ValueError("Baseline must be a directory inside the scenario")
    guidance = (directory / "evaluation/common.md").read_text()
    task_id = slug(task or config["default_task"])
    if task_id not in config["tasks"]:
        raise ValueError(f"Unknown task: {task_id}; choose from {', '.join(config['tasks'])}")
    prompt_path = directory / config["tasks"][task_id]
    guidance += "\n\n" + (directory / "evaluation" / f"{task_id}.md").read_text()
    prompt = prompt_path.read_text().strip()
    if not prompt or config["coding_timeout"] <= 0:
        raise ValueError("Task and positive coding timeout are required")
    return dict(
        config,
        name=slug(config["name"]),
        baseline=baseline,
        prompt=prompt,
        prompt_version=prompt_version(name, task_id, prompt),
        task_name=task_id,
        directory=directory,
        evaluation_guidance=guidance,
    )


PROMPT = load_scenario()["prompt"]


def baseline_archive(baseline):
    # Only baseline files; ignore installed dependencies, build output and local secrets.
    paths = []
    for directory, dirs, files in os.walk(baseline):
        if any((Path(directory) / d).is_symlink() for d in dirs):
            raise ValueError("Baseline directory symlinks are not supported")
        dirs[:] = sorted(
            d
            for d in dirs
            if d
            not in {
                ".git",
                ".venv",
                "node_modules",
                ".terraform",
                "dist",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                "coverage",
            }
        )
        paths.extend(Path(directory) / name for name in files)
    paths.sort()
    # Match the baseline's generated/secret-file exclusions without depending on
    # checkout Git metadata or the user's global ignore configuration.
    excluded = (
        "*.py[cod]",
        "*.tfstate",
        "*.tfstate.*",
        "*.tfplan",
        "*.tfvars",
        ".env",
        ".DS_Store",
    )
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        for path in paths:
            if ".git" in path.relative_to(baseline).parts or any(
                fnmatch.fnmatchcase(path.name, pattern) for pattern in excluded
            ):
                continue
            if path.is_symlink():
                raise ValueError("Baseline symlinks are not supported")
            info = tar.gettarinfo(str(path), arcname=str(path.relative_to(baseline)))
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ""
            with path.open("rb") as file:
                tar.addfile(info, file)
    return data.getvalue()


def result_directory(parent, scenario, task, alias, prompt):
    group = parent / slug(scenario) / slug(task)
    group.mkdir(parents=True, exist_ok=True)
    runs = group / slug(alias) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(prefix=dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ-"), dir=runs)
    )


@contextmanager
def private_probe(result):
    """Remove only the probe created for this invocation, even on failure."""
    path = result / "private-probe"
    with path.open("x") as file:
        file.write("not visible to candidates")
    try:
        yield
    finally:
        path.unlink()


def update_latest(result):
    latest = result.parent.parent / "latest"
    temporary = latest.with_name(".latest-" + result.name)
    temporary.symlink_to(Path("runs") / result.name, target_is_directory=True)
    temporary.replace(latest)


def now():
    return dt.datetime.now(dt.UTC).isoformat()


def redact(text, secret=""):
    if secret:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"sk-or-v1-[A-Za-z0-9_-]+", "[REDACTED]", text)
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~-]+", r"\1[REDACTED]", text)


def save(path, value, secret=""):
    text = value if isinstance(value, str) else json.dumps(value, indent=2) + "\n"
    path.write_text(redact(text, secret))


def command(args, cwd=None, env=None):
    return subprocess.check_output(args, cwd=cwd, env=env, stderr=subprocess.PIPE).decode()


def git_env(home):
    return {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "Developer",
        "GIT_AUTHOR_EMAIL": "developer@example.invalid",
        "GIT_COMMITTER_NAME": "Developer",
        "GIT_COMMITTER_EMAIL": "developer@example.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        "LC_ALL": "en_US.UTF-8",
    }


def prepare(archive, root):
    workspace = root / "project"
    home = root / "home"
    workspace.mkdir()
    home.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        # Reject links and special files rather than risk exporting outside the sandbox.
        for member in tar.getmembers():
            if not (member.isfile() or member.isdir()):
                raise RuntimeError(f"Unsupported archive entry: {member.name}")
            if member.name.startswith("/") or any(
                part in {"..", ".git"} for part in Path(member.name).parts
            ):
                raise RuntimeError("Unsafe archive path")
        tar.extractall(workspace, filter="data")
    env = git_env(home)
    command(["git", "init", "--quiet", "--initial-branch=main", "--template="], workspace, env)
    command(["git", "add", "--all"], workspace, env)
    command(
        ["git", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Initial commit"], workspace, env
    )
    initial = command(["git", "rev-parse", "HEAD"], workspace, env).strip()
    return workspace, home, initial


def sandbox(root, profile_dir=None):
    # Allow system tools, but no user files, other temporary runs, or source checkout.
    reads = [
        "/System",
        "/Library",
        "/usr",
        "/bin",
        "/sbin",
        "/opt/homebrew",
        "/private/etc",
        "/private/var/db",
        "/dev",
        str(root),
    ]
    profile = """(version 1)
(deny default)
(allow process-exec process-fork)
(allow process-info* signal (target same-sandbox))
(allow sysctl-read mach-lookup mach-register ipc-posix-shm* network*)
(allow file-read-metadata)
(allow file-read-data (literal "/"))
"""
    profile += "(allow file-read* " + " ".join(f"(subpath {json.dumps(p)})" for p in reads) + ")\n"
    profile += f'(allow file-write* (subpath {json.dumps(str(root))}) (subpath "/dev"))\n'
    path = (profile_dir or root) / "sandbox.sb"
    path.write_text(profile)
    return ["/usr/bin/sandbox-exec", "-f", str(path)]


def environment(root, home, workspace):
    env = git_env(home)
    env.update(
        {
            "PWD": str(workspace),
            "TMPDIR": str(root / "tmp"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_STATE_HOME": str(home / ".local/state"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "UV_CACHE_DIR": str(home / ".cache/uv"),
            "UV_PYTHON_INSTALL_DIR": str(home / ".local/share/uv/python"),
            "npm_config_cache": str(home / ".npm"),
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER": "1",
            "NO_COLOR": "1",
            "CI": "true",
        }
    )
    (root / "tmp").mkdir()
    return env


def prepare_tools(root, archive):
    """Stage only runtimes, never user configuration or dependency caches."""
    (root / "bin").mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        terraform = (
            tar.extractfile(".terraform-version")
            if ".terraform-version" in tar.getnames()
            else None
        )
        terraform_version = terraform.read().decode().strip() if terraform else None
        node = tar.extractfile(".node-version") if ".node-version" in tar.getnames() else None
        node_version = node.read().decode().strip() if node else None
    if terraform_version:
        binary = Path.home() / ".config/tfenv/versions" / terraform_version / "terraform"
        override = os.environ.get("BENCHMARK_TERRAFORM_BIN")
        if override:
            binary = Path(override).expanduser()
        if not binary.is_file():
            raise RuntimeError("Set BENCHMARK_TERRAFORM_BIN to the pinned Terraform executable")
        shutil.copy2(binary, root / "bin/terraform")
        actual = json.loads(command([str(root / "bin/terraform"), "version", "-json"]))
        if actual["terraform_version"] != terraform_version:
            raise RuntimeError("Terraform version differs from the exported .terraform-version")
    if node_version is None:
        return root
    if not re.fullmatch(r"\d+\.\d+\.\d+", node_version):
        raise ValueError("Exported .node-version must contain an exact Node version")
    arch = "arm64" if os.uname().machine == "arm64" else "x64"
    filename = f"node-v{node_version}-darwin-{arch}.tar.gz"
    base = f"https://nodejs.org/dist/v{node_version}/"
    with urllib.request.urlopen(base + "SHASUMS256.txt", timeout=30) as response:
        hashes = dict(line.split()[::-1] for line in response.read().decode().splitlines())
    with urllib.request.urlopen(base + filename, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != hashes[filename]:
        raise RuntimeError("Node archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(root, filter="data")
    (root / filename.removesuffix(".tar.gz")).rename(root / "node")
    if command([str(root / "node/bin/node"), "--version"]).strip() != "v" + node_version:
        raise RuntimeError("Staged Node version differs from .node-version")
    return root


def configuration(model, endpoint):
    # Explicit entry also supports exact IDs missing from OpenCode's bundled catalog.
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": "openrouter/" + model,
        "small_model": "openrouter/" + model,
        "enabled_providers": ["openrouter"],
        "autoupdate": False,
        "share": "disabled",
        "plugin": [],
        "mcp": {},
        "lsp": False,
        "formatter": False,
        "permission": {
            "*": "deny",
            "read": "allow",
            "edit": "deny",
            "write": "deny",
            "apply_patch": "deny",
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
            "bash": "allow",
            "todowrite": "allow",
            "external_directory": "deny",
        },
        "agent": {"title": {"disable": True}},
        "provider": {
            "openrouter": {
                "npm": "@openrouter/ai-sdk-provider",
                "options": {"baseURL": endpoint, "apiKey": "local-relay-no-secret"},
                "models": {
                    model: {
                        "id": model,
                        "name": model,
                        "tool_call": True,
                        "reasoning": True,
                        "limit": {"context": 131072, "output": 16384},
                    }
                },
            }
        },
    }


def execute(args, cwd, env, timeout, stdin=None):
    started = time.monotonic()
    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    finally:
        # Also remove background tools left behind after a normal agent exit.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return process.returncode, time.monotonic() - started, timed_out, stdout, stderr


class Relay(http.server.ThreadingHTTPServer):
    """Credential boundary and usage recorder; never stores requests or headers."""

    daemon_threads = True

    def __init__(self, model, key, upstream=API, *, provider=None):
        super().__init__(("127.0.0.1", 0), RelayHandler)
        self.model, self.key, self.upstream = model, key, upstream
        self.provider_routing = (
            {"only": [provider], "allow_fallbacks": False} if provider is not None else None
        )
        self.calls = []
        self.lock = threading.Lock()
        self.active = True

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.calls)


class RelayHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        relay = self.server
        if self.path != "/api/v1/chat/completions" or not relay.active:
            self.send_error(403)
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body.get("model") != relay.model or body.get("models") or body.get("route"):
                self.send_error(400, "Unexpected model or routing override")
                return
            # Ignore client/SDK overrides so OpenRouter uses each model's defaults.
            for field in ("reasoning", "reasoning_effort", "include_reasoning"):
                body.pop(field, None)
            body["usage"] = {"include": True}
            if relay.provider_routing is not None:
                body["provider"] = copy.deepcopy(relay.provider_routing)
            record = {
                "started_at": now(),
                "requested_model": relay.model,
                "provider_routing": copy.deepcopy(body.get("provider")),
                "reasoning": None,
                "reasoning_policy": "model_default",
                "http_status": None,
                "generation_id": None,
                "model": None,
                "provider": None,
                "usage": None,
                "stream_complete": False,
            }
            with relay.lock:
                relay.calls.append(record)
            request = urllib.request.Request(
                relay.upstream + "/chat/completions",
                json.dumps(body).encode(),
                {
                    "Authorization": "Bearer " + relay.key,
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://opencode.ai/",
                    "X-Title": "OpenCode benchmark",
                },
            )
            try:
                response = urllib.request.urlopen(request, timeout=TIMEOUT)
            except urllib.error.HTTPError as error:
                with relay.lock:
                    record["http_status"] = error.code
                self.send_response(error.code)
                self.end_headers()
                self.wfile.write(redact(error.read().decode(errors="replace"), relay.key).encode())
                return
            with response:
                with relay.lock:
                    record["http_status"] = response.status
                self.send_response(response.status)
                self.send_header(
                    "Content-Type", response.headers.get("Content-Type", "text/event-stream")
                )
                self.end_headers()
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    for line in response:
                        line = redact(line.decode(errors="replace"), relay.key).encode()
                        self.capture(line, record)
                        self.wfile.write(line)
                        self.wfile.flush()
                else:
                    data = response.read()
                    self.capture(b"data: " + data, record)
                    self.wfile.write(data)
        except (OSError, ValueError, KeyError):
            # No exception text: HTTP errors may embed request credentials.
            self.close_connection = True

    def capture(self, line, record):
        if not line.startswith(b"data:"):
            return
        data = line[5:].strip()
        with self.server.lock:
            if data == b"[DONE]":
                record["stream_complete"] = True
                return
            try:
                event = json.loads(data)
            except ValueError:
                return
            for src, dst in [("id", "generation_id"), ("model", "model"), ("provider", "provider")]:
                if event.get(src) is not None:
                    record[dst] = event[src]
            if event.get("usage") is not None:
                record["usage"] = event["usage"]  # Last snapshot, never sum streaming snapshots.
            if event.get("error"):
                record["api_error"] = True


def enrich_calls(calls, key, upstream):
    """Read-only metadata lookup when a stream omitted billed cost or routing data."""
    for call in calls:
        usage = call.get("usage") or {}
        if not call.get("generation_id") or (
            call.get("model") and call.get("provider") and usage.get("cost") is not None
        ):
            continue
        query = urllib.parse.urlencode({"id": call["generation_id"]})
        request = urllib.request.Request(
            upstream + "/generation?" + query, headers={"Authorization": "Bearer " + key}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.load(response)["data"]
            call["generation"] = {
                field: data.get(field)
                for field in [
                    "id",
                    "model",
                    "provider_name",
                    "total_cost",
                    "native_tokens_prompt",
                    "native_tokens_completion",
                    "native_tokens_reasoning",
                ]
            }
            call["model"] = data.get("model") or call.get("model")
            call["provider"] = data.get("provider_name") or call.get("provider")
            if usage.get("cost") is None and data.get("total_cost") is not None:
                usage["cost"] = data["total_cost"]
                call["usage"] = usage
        except (OSError, ValueError, KeyError):
            call["generation_lookup"] = "unavailable"


def usage_metrics(calls):
    def total(*path):
        values = []
        for call in calls:
            value = call.get("usage")
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return None
            values.append(value)
        return sum(values) if values else None

    return {
        "api_calls": len(calls),
        "actual_served_model_id": (
            calls[0].get("model")
            if calls and all(c.get("model") == calls[0].get("model") for c in calls)
            else None
        ),
        "actual_served_models": sorted({c["model"] for c in calls if c.get("model")}) or None,
        "actual_providers": sorted({c["provider"] for c in calls if c.get("provider")}) or None,
        "actual_cost_usd": total("cost"),
        "input_tokens": total("prompt_tokens"),
        "output_tokens": total("completion_tokens"),
        "cache_read_tokens": total("prompt_tokens_details", "cached_tokens"),
        "cache_write_tokens": total("prompt_tokens_details", "cache_write_tokens"),
        "reasoning_tokens": total("completion_tokens_details", "reasoning_tokens"),
    }


def collect_diff(workspace, initial, env, result, prefix=()):
    # Use a separate index: candidate commits/staging cannot hide their final changes.
    env = dict(env, GIT_INDEX_FILE=str(workspace.parent / "review-index"))
    command([*prefix, "git", "read-tree", initial], workspace, env)
    command([*prefix, "git", "add", "-A", "--", "."], workspace, env)
    base = [
        *prefix,
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "diff",
        "--cached",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        initial,
    ]
    save(result / "diff.patch", command(base + ["--binary"], workspace, env))
    entries = command(base + ["--numstat", "-z"], workspace, env).split("\0")
    counts = [e.split("\t", 2)[:2] for e in entries if e]
    return {
        "changed_files": len(counts),
        "inserted_lines": sum(int(a) for a, _ in counts if a != "-"),
        "deleted_lines": sum(int(b) for _, b in counts if b != "-"),
    }


def credential():
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    path = data / "opencode/auth.json"
    try:
        auth = json.loads(path.read_text()).get("openrouter", {})
        if auth.get("type") == "api" and auth.get("key"):
            return auth["key"]
    except (OSError, ValueError):
        pass
    raise RuntimeError("Set OPENROUTER_API_KEY or authenticate with opencode auth login.")


def probe(prefix, workspace, env, source, result):
    script = (
        "test -r README.md && test -w . && "
        'test ! -r "$1/HEAD" && test ! -r "$2" && '
        'test ! -r "$3" && printf sandbox-ok'
    )
    output = command(
        prefix
        + [
            "/bin/bash",
            "-c",
            script,
            "probe",
            str(source / ".git"),
            str(result / "private-probe"),
            str(Path.home() / ".zsh_history"),
        ],
        workspace,
        env,
    )
    if output != "sandbox-ok":
        raise RuntimeError("Sandbox isolation probe failed")


def run_candidate(
    alias,
    archive,
    output,
    binary,
    key,
    dry_run=False,
    upstream=API,
    tools=None,
    available=True,
    scenario=None,
    result=None,
    task_dir=None,
):
    if result is None:
        result = output / alias
        result.mkdir()
    prompt = scenario["prompt"] if scenario else PROMPT
    timeout_seconds = scenario["coding_timeout"] if scenario else TIMEOUT
    validation = scenario["validation_command"] if scenario else "bash scripts/check.sh"
    provider = PROVIDERS.get(alias)
    provider_routing = (
        {"only": [provider], "allow_fallbacks": False} if provider is not None else None
    )
    source_hashes = {"task.md": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
    if scenario:
        source_hashes["evaluation-guidance.md"] = hashlib.sha256(
            scenario["evaluation_guidance"].encode("utf-8")
        ).hexdigest()
    save(
        result / "run.json",
        {
            "scenario": scenario["name"] if scenario else "fixture",
            "task_name": scenario["task_name"] if scenario else "fixture",
            "model": alias,
            "prompt": prompt,
            "evaluation_guidance": scenario["evaluation_guidance"] if scenario else None,
            "prompt_version": scenario.get("prompt_version") if scenario else None,
            "dry_run": dry_run,
            "reasoning_policy": "model_default",
            "provider_routing": provider_routing,
            "allowed_tools": [
                name
                for name, permission in configuration(MODELS[alias], "")["permission"].items()
                if permission == "allow"
            ],
            "archive_sha256": hashlib.sha256(archive).hexdigest(),
            "source_sha256": source_hashes,
            "validation_command": validation,
            "coding_timeout": timeout_seconds,
        },
    )
    metrics = {
        "model": alias,
        "requested_model_id": MODELS[alias],
        "provider_routing": provider_routing,
        "provider": "openrouter",
        "opencode_version": scenario.get("opencode_version", VERSION) if scenario else VERSION,
        "started_at": now(),
        "ended_at": None,
        "status": "failed",
        "timeout": False,
        "coding_duration_seconds": None,
        "validation_duration_seconds": None,
        "opencode_exit_status": None,
        "validation_exit_status": None,
        "validation": "UNAVAILABLE",
        "model_calls": None,
        "changed_files": None,
        "inserted_lines": None,
        "deleted_lines": None,
        "reasoning_effort": None,
        "reasoning_policy": "model_default",
        "timeout_seconds": timeout_seconds,
        **usage_metrics([]),
    }
    for name in [
        "response.txt",
        "transcript.jsonl",
        "diff.patch",
        "check.log",
    ]:
        save(result / name, "")
    try:
        if not available:
            raise RuntimeError("Exact requested model is unavailable in the OpenRouter catalog")
        with tempfile.TemporaryDirectory(prefix="coding-task-") as temp:
            root = Path(temp).resolve()
            workspace, home, initial = prepare(archive, root)
            env = environment(root, home, workspace)
            if tools:
                shutil.copytree(tools, root / "tools", symlinks=True)
                env["PATH"] = (
                    str(root / "tools/node/bin") + ":" + str(root / "tools/bin") + ":" + env["PATH"]
                )
            prefix = sandbox(root)
            probe(prefix, workspace, env, ROOT, output)
            relay = Relay(MODELS[alias], key, upstream, provider=provider)
            config = configuration(MODELS[alias], f"http://127.0.0.1:{relay.server_port}/api/v1")
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
            if dry_run:
                # Resolve config and model syntax, but never invoke `run` or a generation endpoint.
                resolved = command(
                    prefix + [binary, "models", "openrouter", "--pure"], workspace, env
                )
                if "openrouter/" + MODELS[alias] not in resolved.splitlines():
                    raise RuntimeError("Exact model not resolved by OpenCode")
                metrics["status"] = "prepared"
                metrics["initial_commit"] = initial
                metrics.update(collect_diff(workspace, initial, env, result, prefix))
                relay.server_close()
            else:
                thread = threading.Thread(target=relay.serve_forever, daemon=True)
                thread.start()
                try:
                    metrics["coding_started_at"] = now()
                    code, duration, timeout, stdout, stderr = execute(
                        prefix
                        + [
                            binary,
                            "run",
                            "--pure",
                            "--agent",
                            "build",
                            "--format",
                            "json",
                            "--thinking",
                            "--model",
                            "openrouter/" + MODELS[alias],
                            "--title",
                            "Coding task",
                        ],
                        workspace,
                        env,
                        timeout_seconds,
                        prompt.encode(),
                    )
                    metrics["coding_ended_at"] = now()
                finally:
                    relay.active = False
                    relay.shutdown()
                    relay.server_close()
                    thread.join()
                calls = relay.snapshot()
                enrich_calls(calls, key, upstream)
                save(result / "api-calls.json", calls, key)
                metrics.update(usage_metrics(calls))
                metrics.update(
                    opencode_exit_status=code, coding_duration_seconds=duration, timeout=timeout
                )
                transcript = stdout.decode(errors="replace")
                save(result / "transcript.jsonl", transcript, key)
                if stderr:
                    save(result / "opencode.log", stderr.decode(errors="replace"), key)
                events = []
                for line in transcript.splitlines():
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        pass
                texts = {
                    e["part"]["id"]: e["part"].get("text", "")
                    for e in events
                    if e.get("type") == "text"
                }
                save(result / "response.txt", "\n\n".join(texts.values()), key)
                metrics["model_calls"] = len(
                    {e["part"]["id"] for e in events if e.get("type") == "step_finish"}
                )
                metrics["api_errors"] = extract_api_errors(events, key)
                errors = any(e.get("type") == "error" for e in events)
                metrics["status"] = (
                    "timed-out"
                    if timeout
                    else "completed"
                    if code == 0 and texts and not errors
                    else "failed"
                )
                try:
                    metrics.update(collect_diff(workspace, initial, env, result, prefix))
                except subprocess.CalledProcessError:
                    metrics["diff_error"] = "Unable to collect final Git diff"
                    metrics["status"] = "failed" if not timeout else "timed-out"
                # New process, independent of the agent's claims, even after failure/timeout.
                metrics["validation_started_at"] = now()
                code, duration, timeout, stdout, stderr = execute(
                    prefix + ["/bin/bash", "-c", validation], workspace, env, TIMEOUT
                )
                metrics["validation_ended_at"] = now()
                save(
                    result / "check.log",
                    stdout.decode(errors="replace")
                    + "\n--- stderr ---\n"
                    + stderr.decode(errors="replace"),
                    key,
                )
                metrics.update(
                    validation_exit_status=code,
                    validation_duration_seconds=duration,
                    validation="PASS" if code == 0 else "FAIL",
                    validation_timeout=timeout,
                )
    except Exception as error:
        # Avoid traceback/env/request dumps, which can disclose secrets.
        metrics["failure"] = redact(f"{type(error).__name__}: {error}", key)
    metrics["ended_at"] = now()
    save(result / "metrics.json", metrics, key)
    if result.parent.name == "runs":
        update_latest(result)
    print_summary(metrics)
    return metrics


def extract_api_errors(events, key):
    errors = []
    for event in events:
        if event.get("type") != "error":
            continue
        error = event.get("error")
        if not isinstance(error, dict) or error.get("name") != "APIError":
            continue
        data = error.get("data")
        if not isinstance(data, dict):
            continue
        message = data.get("message")
        status = data.get("statusCode")
        errors.append(
            {
                "status_code": status if type(status) is int else None,
                "message": redact(message, key)
                if isinstance(message, str)
                else "Unknown API error",
            }
        )
    return errors


def print_summary(m):
    cost = "unavailable" if m["actual_cost_usd"] is None else f"${m['actual_cost_usd']:.6f}"
    duration = m["coding_duration_seconds"]
    elapsed = "n/a" if duration is None else f"{duration:.1f}s"
    print(
        f"{m['model']:9} {m['status']:10} check={m['validation']:11} coding={elapsed} cost={cost}"
    )
    for error in m.get("api_errors", []):
        status = error["status_code"]
        label = "API error" if status is None else f"API error {status}"
        print(f"  {label}: {' '.join(error['message'].split())}")
    if m.get("failure"):
        print("  " + m["failure"])


def check_runtime():
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        raise RuntimeError(
            "This runner requires macOS sandbox-exec; it will not run without isolation"
        )
    binary = shutil.which("opencode")
    if binary:
        binary = str(Path(binary).resolve())
    if not binary:
        raise RuntimeError("OpenCode is not installed or not on PATH")
    actual = command([binary, "--version"]).strip()
    if actual != VERSION:
        print(f"Warning: OpenCode {actual}; tested with {VERSION}", file=sys.stderr)
    return binary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", nargs="?", choices=[*MODELS, "all"])
    parser.add_argument(
        "--dry-run", action="store_true", help="prepare and inspect only; no model calls"
    )
    parser.add_argument("--scenario", default="field-notes")
    parser.add_argument("--task", help="task name (default: scenario default_task)")
    args = parser.parse_args(argv)
    try:
        scenario = load_scenario(args.scenario, task=args.task)
    except ValueError as error:
        parser.error(str(error))
    if args.model is None:
        options = [*MODELS, "all"]
        for i, alias in enumerate(options, 1):
            print(f"{i}. {alias}" + (f" = {MODELS[alias]}" if alias in MODELS else ""))
        try:
            choice = input("Model (name or number): ").strip().lower()
        except EOFError:
            parser.error("Select a model argument when stdin is not interactive")
        args.model = (
            options[int(choice) - 1]
            if choice.isdigit() and 1 <= int(choice) <= len(options)
            else choice
        )
        if args.model not in options:
            parser.error("Unknown model")
    parent = ROOT / "results"
    binary = check_runtime()
    scenario["opencode_version"] = command([binary, "--version"]).strip()
    aliases = list(MODELS) if args.model == "all" else [args.model]
    # Export once before any candidate starts. No Git history enters the temporary repository.
    archive = baseline_archive(scenario["baseline"])
    os.umask(0o077)
    task_dir = parent / scenario["name"] / scenario["task_name"]

    key = "" if args.dry_run else credential()
    catalog = set(MODELS.values())
    if not args.dry_run:
        with urllib.request.urlopen(API + "/models", timeout=30) as response:
            catalog = {m["id"] for m in json.load(response)["data"]}
    # Results remain outside every candidate's temporary sandbox.
    parent.mkdir(parents=True, exist_ok=True)
    summaries = []
    with tempfile.TemporaryDirectory(prefix="coding-tools-") as tool_temp:
        tools = None if args.dry_run else prepare_tools(Path(tool_temp), archive)
        for alias in aliases:
            result = result_directory(
                parent, scenario["name"], scenario["task_name"], alias, scenario["prompt"]
            )
            print(f"Prompt version: {scenario.get('prompt_version') or 'unversioned'}", flush=True)
            print(f"Results: {result}", flush=True)
            with private_probe(result):
                summaries.append(
                    run_candidate(
                        alias,
                        archive,
                        result,
                        binary,
                        key,
                        args.dry_run,
                        tools=tools,
                        available=MODELS[alias] in catalog,
                        scenario=scenario,
                        result=result,
                        task_dir=task_dir,
                    )
                )
    return (
        0
        if all(
            m["status"] in {"completed", "prepared"} and (args.dry_run or m["validation"] == "PASS")
            for m in summaries
        )
        else 1
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Benchmark setup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
