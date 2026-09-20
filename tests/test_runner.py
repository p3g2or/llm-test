"""Offline tests. Optional integration uses real OpenCode against a fake local API."""

import io
import json
import os
import shutil
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from support import evaluate, runner


def fixture_archive(node_version=None):
    files = {
        "README.md": "Fixture repository\n",
        "scripts/check.sh": "#!/bin/bash\ntest -f regression.txt\necho independent-check\n",
    }
    if node_version is not None:
        files[".node-version"] = node_version + "\n"
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        for name, text in files.items():
            content = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o644
            tar.addfile(member, io.BytesIO(content))
    return data.getvalue()


class ArtifactLayoutTests(unittest.TestCase):
    def test_archive_is_git_independent_and_excludes_generated_or_secret_files(self):
        with tempfile.TemporaryDirectory() as temp:
            baseline = Path(temp)
            included = ("src/app.py", "dev.tfvars.example", ".gitignore", "scripts/check.sh")
            excluded = (
                ".git/config",
                "node_modules/pkg/index.js",
                ".venv/bin/python",
                "dist/app.js",
                "__pycache__/app.pyc",
                "app.pyc",
                "app.pyo",
                "app.pyd",
                "dev.tfvars",
                "terraform.tfstate",
                "terraform.tfstate.backup",
                "dev.tfplan",
                ".env",
                ".DS_Store",
            )
            for name in included + excluded:
                path = baseline / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            with patch("runner.subprocess.run", side_effect=AssertionError("Git is forbidden")):
                archive = runner.baseline_archive(baseline)
                self.assertEqual(archive, runner.baseline_archive(baseline))
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                self.assertEqual(tar.getnames(), sorted(included))
                for member in tar.getmembers():
                    self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
                    self.assertEqual(tar.extractfile(member).read(), member.name.encode())
            (baseline / "link").symlink_to(baseline / "src/app.py")
            with self.assertRaisesRegex(ValueError, "symlinks"):
                runner.baseline_archive(baseline)

    def test_candidates_keep_inputs_only_in_scenario_sources(self):
        scenario = runner.load_scenario()
        archive = fixture_archive()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "results"
            task = root / scenario["name"] / scenario["task_name"]
            for alias in ("glm", "opus"):
                run = runner.result_directory(
                    root, scenario["name"], scenario["task_name"], alias, scenario["prompt"]
                )
                with patch("runner.prepare") as prepare:
                    runner.run_candidate(
                        alias,
                        archive,
                        run,
                        "/unused",
                        "",
                        available=False,
                        scenario=scenario,
                        result=run,
                        task_dir=task,
                    )
                prepare.assert_not_called()
                for name in ("task.md", "evaluation-guidance.md", "baseline.tar"):
                    self.assertFalse((run / name).exists())
                    self.assertFalse((run / name).is_symlink())
                metadata = json.loads((run / "run.json").read_text())
                self.assertEqual(metadata["archive_sha256"], evaluate.digest(archive))
                self.assertEqual(
                    metadata["source_sha256"],
                    {
                        "task.md": evaluate.digest(scenario["prompt"].encode()),
                        "evaluation-guidance.md": evaluate.digest(
                            scenario["evaluation_guidance"].encode()
                        ),
                    },
                )
            for name in ("task.md", "evaluation-guidance.md", "baseline.tar"):
                self.assertEqual(list(root.rglob(name)), [])

    def test_private_probe_cleanup_on_success_failure_and_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            result = Path(temp)
            probe = result / "private-probe"
            with runner.private_probe(result):
                self.assertTrue(probe.is_file())
            self.assertFalse(probe.exists())
            with self.assertRaisesRegex(RuntimeError, "failed"):
                with runner.private_probe(result):
                    raise RuntimeError("failed")
            self.assertFalse(probe.exists())
            probe.write_text("historical")
            with self.assertRaises(FileExistsError):
                with runner.private_probe(result):
                    self.fail("must not replace an existing probe")
            self.assertEqual(probe.read_text(), "historical")

    def test_flat_candidate_does_not_persist_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            runner.run_candidate(
                "glm",
                fixture_archive(),
                output,
                "/unused",
                "",
                available=False,
                scenario=runner.load_scenario(),
            )
            for name in ("task.md", "evaluation-guidance.md", "baseline.tar"):
                self.assertFalse((output / "glm" / name).exists())
                self.assertEqual(list(output.rglob(name)), [])


class RunnerTests(unittest.TestCase):
    def test_arguments_reject_unknown_without_side_effects(self):
        with patch("runner.credential") as auth, self.assertRaises(SystemExit) as exit:
            runner.main(["unknown"])
        self.assertEqual(exit.exception.code, 2)
        auth.assert_not_called()

    def test_removed_options_fail_before_running_anything(self):
        for flag in ("--task-file", "--task-name", "--results-dir"):
            with (
                self.subTest(flag=flag),
                patch("runner.check_runtime") as runtime,
                self.assertRaises(SystemExit) as error,
            ):
                runner.main(["sol", flag, "unused"])
            self.assertEqual(error.exception.code, 2)
            runtime.assert_not_called()

    def test_prompt_changes_do_not_block_new_run_or_rewrite_history(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            old = runner.result_directory(parent, "field-notes", "known-bug", "glm", "old")
            metadata = old / "run.json"
            metadata.write_text('{"prompt":"old","prompt_version":"v1"}')
            before = metadata.read_bytes()
            new = runner.result_directory(
                parent, "field-notes", "known-bug", "sol", "new unregistered text"
            )
            self.assertTrue(new.is_dir())
            self.assertNotEqual(old, new)
            self.assertEqual(metadata.read_bytes(), before)

    def test_evaluate_defaults_to_repo_results_without_model_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            run = root / "results/scenario/task/model/runs/attempt"
            run.mkdir(parents=True)
            (run / "run.json").write_text("{}")
            (run / "metrics.json").write_text(
                json.dumps({"ended_at": "2026-01-01T00:00:00Z", "status": "completed"})
            )
            (run.parents[1] / "latest").symlink_to("runs/attempt")
            with (
                patch("runner.ROOT", root),
                patch("evaluate.discover_comparison", return_value=[run]) as discover,
                patch("evaluate.comparison_identity", return_value={"config": {}, "runs": []}),
                patch("evaluate.prepare_evidence", return_value=({}, {"files": [], "missing": []})),
                patch("evaluate.request_assessment") as assessment,
                patch("runner.credential") as auth,
                patch("evaluate.urllib.request.urlopen") as network,
            ):
                self.assertEqual(evaluate.main(["all", "--dry-run"]), 0)
            discover.assert_called_once_with(str(root / "results/scenario/task"), root / "results")
            assessment.assert_not_called()
            auth.assert_not_called()
            network.assert_not_called()
            self.assertFalse((root / "evaluations").exists())

    def test_sandbox_profile_does_not_allow_source_or_local_results(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            candidate = parent / "candidate"
            candidate.mkdir()
            results = parent / "repo/results"
            results.mkdir(parents=True)
            runner.sandbox(candidate, results)
            profile = (results / "sandbox.sb").read_text()
            self.assertIn("(deny default)", profile)
            self.assertIn(f"(subpath {json.dumps(str(candidate))})", profile)
            self.assertNotIn(str(results), profile)
            self.assertNotIn(str(runner.ROOT), profile)

    def test_preparation_has_one_neutral_commit_and_no_refs_or_remotes(self):
        commits = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace, home, initial = runner.prepare(fixture_archive(), root)
                env = runner.git_env(home)
                commits.append(initial)
                self.assertEqual(
                    runner.command(["git", "log", "--format=%s"], workspace, env),
                    "Initial commit\n",
                )
                self.assertEqual(runner.command(["git", "tag"], workspace, env), "")
                self.assertEqual(runner.command(["git", "remote"], workspace, env), "")
                self.assertEqual(
                    runner.command(["git", "branch", "--format=%(refname:short)"], workspace, env),
                    "main\n",
                )
        self.assertEqual(commits[0], commits[1])

    def test_diff_includes_untracked_regression_and_candidate_commits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace, home, initial = runner.prepare(fixture_archive(), root)
            env = runner.git_env(home)
            (workspace / "README.md").write_text("Changed\n")
            runner.command(["git", "commit", "-am", "Candidate edit"], workspace, env)
            (workspace / "regression.txt").write_text("Regression\n")
            result = root / "result"
            result.mkdir()
            metrics = runner.collect_diff(workspace, initial, env, result)
            self.assertEqual(metrics, {"changed_files": 2, "inserted_lines": 2, "deleted_lines": 1})
            self.assertIn("+Regression", (result / "diff.patch").read_text())
            self.assertIn("+Changed", (result / "diff.patch").read_text())

    def test_usage_missing_is_null_and_actual_zero_is_zero(self):
        self.assertIsNone(runner.usage_metrics([])["actual_cost_usd"])
        call = {
            "usage": {
                "cost": 0,
                "prompt_tokens": 17,
                "completion_tokens": 8,
                "prompt_tokens_details": {"cached_tokens": 4},
                "completion_tokens_details": {"reasoning_tokens": 3},
            }
        }
        metrics = runner.usage_metrics([call])
        self.assertEqual(metrics["actual_cost_usd"], 0)
        self.assertEqual(metrics["input_tokens"], 17)
        self.assertIsNone(metrics["cache_write_tokens"])
        self.assertIsNone(runner.usage_metrics([call, {"usage": None}])["actual_cost_usd"])

    def test_stream_usage_snapshots_are_not_double_counted(self):
        server = runner.Relay("example/model", "not-a-real-key")
        try:
            handler = object.__new__(runner.RelayHandler)
            handler.server = server
            record = {}
            for tokens in [10, 20]:
                handler.capture(
                    b"data: "
                    + json.dumps(
                        {"usage": {"prompt_tokens": tokens}, "model": "served/model"}
                    ).encode(),
                    record,
                )
            self.assertEqual(runner.usage_metrics([record])["input_tokens"], 20)
            self.assertEqual(
                runner.usage_metrics([record])["actual_served_models"], ["served/model"]
            )
        finally:
            server.server_close()

    def test_generation_fallback_records_cost_without_inventing_token_totals(self):
        call = {"generation_id": "gen-test", "usage": None}
        response = io.BytesIO(
            json.dumps(
                {
                    "data": {
                        "model": "actual/model",
                        "provider_name": "ActualProvider",
                        "total_cost": 0.12,
                        "native_tokens_prompt": 99,
                    }
                }
            ).encode()
        )
        with patch("runner.urllib.request.urlopen", return_value=response):
            runner.enrich_calls([call], "fixture-key", "http://fixture.invalid")
        metrics = runner.usage_metrics([call])
        self.assertEqual(metrics["actual_cost_usd"], 0.12)
        self.assertEqual(metrics["actual_providers"], ["ActualProvider"])
        self.assertIsNone(metrics["input_tokens"])
        self.assertEqual(call["generation"]["native_tokens_prompt"], 99)

    def test_missing_catalog_model_fails_without_calling_agent(self):
        with tempfile.TemporaryDirectory() as temp, patch("runner.execute") as execute:
            metrics = runner.run_candidate(
                "auto", fixture_archive(), Path(temp), "unused", "", available=False
            )
        self.assertEqual(metrics["status"], "failed")
        execute.assert_not_called()

    def test_added_models_and_auto_remain_common_candidates(self):
        expected = {
            "minimax": "minimax/minimax-m3",
            "qwen-flash": "qwen/qwen3.8-flash",
            "sol": "openai/gpt-5.6-sol",
            "sonnet": "anthropic/claude-sonnet-5",
            "kimi": "moonshotai/kimi-k3",
            "auto": "openrouter/auto-beta",
        }
        for alias, model in expected.items():
            self.assertEqual(runner.MODELS[alias], model)

    def test_configuration_does_not_select_reasoning_variant(self):
        for model in runner.MODELS.values():
            with self.subTest(model=model):
                config = runner.configuration(model, "http://fixture.invalid")
                self.assertNotIn("variant", config["agent"].get("build", {}))
                entry = config["provider"]["openrouter"]["models"][model]
                self.assertNotIn("variants", entry)

    def test_provider_config_preserves_model_aliases(self):
        self.assertEqual(runner.PROVIDERS, {"gemini": "google-vertex/global"})
        self.assertTrue(all(isinstance(model, str) for model in runner.MODELS.values()))

    def test_relay_enforces_pin_on_every_request_and_preserves_unpinned_routing(self):
        pin = {"only": ["google-vertex/global"], "allow_fallbacks": False}
        conflict = {"only": ["other"], "order": ["other"], "allow_fallbacks": True}
        for provider in ["google-vertex/global", None]:
            with self.subTest(provider=provider):
                # The third positional argument must remain the upstream URL.
                relay = runner.Relay(
                    "example/model", "fixture-key", "http://fixture.invalid", provider=provider
                )
                self.addCleanup(relay.server_close)
                for incoming in [None, conflict, {"sort": "price"}]:
                    for failed in [False, True]:
                        body = {"model": relay.model, "messages": []}
                        if failed:
                            body.update(
                                reasoning={"effort": "high", "max_tokens": 2048, "enabled": True},
                                reasoning_effort="low",
                                include_reasoning=False,
                            )
                        if incoming is not None:
                            body["provider"] = incoming
                        handler = object.__new__(runner.RelayHandler)
                        handler.server = relay
                        handler.path = "/api/v1/chat/completions"
                        encoded = json.dumps(body).encode()
                        handler.headers = {"Content-Length": str(len(encoded))}
                        handler.rfile = io.BytesIO(encoded)
                        handler.wfile = io.BytesIO()
                        response = io.BytesIO(b'{"provider": "Google", "model": "example/model"}')
                        response.status = 200
                        response.headers = {"Content-Type": "application/json"}
                        error = runner.urllib.error.HTTPError(
                            "http://fixture.invalid", 503, "Unavailable", {}, io.BytesIO(b"failed")
                        )
                        with (
                            patch.object(handler, "send_response"),
                            patch.object(handler, "send_header"),
                            patch.object(handler, "end_headers"),
                            patch(
                                "runner.urllib.request.urlopen",
                                return_value=response,
                                side_effect=error if failed else None,
                            ) as upstream,
                        ):
                            handler.do_POST()
                        request = upstream.call_args.args[0]
                        self.assertEqual(
                            request.full_url, "http://fixture.invalid/chat/completions"
                        )
                        sent = json.loads(request.data)
                        for field in ("reasoning", "reasoning_effort", "include_reasoning"):
                            self.assertNotIn(field, sent)
                        expected = pin if provider else incoming
                        self.assertEqual(sent.get("provider"), expected)
                        if expected is None:
                            self.assertNotIn("provider", sent)
                        record = relay.snapshot()[-1]
                        self.assertEqual(record["provider_routing"], expected)
                        self.assertIsNone(record["reasoning"])
                        self.assertEqual(record["reasoning_policy"], "model_default")
                        self.assertEqual(record["http_status"], 503 if failed else 200)
                        self.assertEqual(record["provider"], None if failed else "Google")
                self.assertEqual(len(relay.snapshot()), 6)

    def test_provider_routing_metadata_for_failed_and_dry_runs(self):
        for alias in ["gemini", "glm"]:
            for available in [False, True]:
                with (
                    self.subTest(alias=alias, available=available),
                    tempfile.TemporaryDirectory() as temp,
                ):
                    output = Path(temp)
                    with (
                        patch("runner.prepare", return_value=(output, output, "initial")),
                        patch("runner.environment", return_value={}),
                        patch("runner.sandbox", return_value=[]),
                        patch("runner.probe"),
                        patch("runner.command", return_value="openrouter/" + runner.MODELS[alias]),
                        patch("runner.collect_diff", return_value={}),
                        patch("runner.Relay", wraps=runner.Relay) as relay,
                        patch("runner.urllib.request.urlopen") as network,
                        patch("runner.execute") as execute,
                    ):
                        metrics = runner.run_candidate(
                            alias,
                            fixture_archive(),
                            output,
                            "unused",
                            "",
                            True,
                            "http://fixture.invalid",
                            available=available,
                        )
                    expected = (
                        {"only": ["google-vertex/global"], "allow_fallbacks": False}
                        if alias == "gemini"
                        else None
                    )
                    self.assertEqual(metrics["status"], "prepared" if available else "failed")
                    self.assertIsNone(metrics["reasoning_effort"])
                    for name in ["run.json", "metrics.json"]:
                        saved = json.loads((output / alias / name).read_text())
                        self.assertEqual(saved["reasoning_policy"], "model_default")
                        self.assertIn("provider_routing", saved)
                        self.assertEqual(saved["provider_routing"], expected)
                    if available:
                        relay.assert_called_once_with(
                            runner.MODELS[alias],
                            "",
                            "http://fixture.invalid",
                            provider=runner.PROVIDERS.get(alias),
                        )
                    else:
                        relay.assert_not_called()
                    network.assert_not_called()
                    execute.assert_not_called()

    def test_credentials_are_redacted(self):
        result = runner.redact(
            "custom-secret sk-or-v1-abc123 Authorization: Bearer token123", "custom-secret"
        )
        for secret in ["custom-secret", "abc123", "token123"]:
            self.assertNotIn(secret, result)

    def test_timeout_captures_output(self):
        code, duration, timeout, stdout, _ = runner.execute(
            ["/bin/bash", "-c", "echo before-timeout; sleep 30"], None, None, 0.1
        )
        self.assertTrue(timeout)
        self.assertLess(duration, 5)
        self.assertNotEqual(code, 0)
        self.assertIn(b"before-timeout", stdout)

    def test_api_errors_are_redacted_and_ignore_unrelated_events(self):
        events = [
            {"type": "text"},
            {"type": "error", "error": None},
            {"type": "error", "error": {"name": "OtherError"}},
            {"type": "error", "error": {"name": "APIError", "data": None}},
            {
                "type": "error",
                "error": {
                    "name": "APIError",
                    "data": {
                        "statusCode": 403,
                        "message": "Budget exceeded: custom-secret",
                    },
                },
            },
            {"type": "error", "error": {"name": "APIError", "data": {}}},
        ]
        errors = runner.extract_api_errors(events, "custom-secret")
        self.assertEqual(len(errors), 2)
        self.assertEqual(errors[0]["status_code"], 403)
        self.assertNotIn("custom-secret", errors[0]["message"])
        self.assertEqual(errors[1], {"status_code": None, "message": "Unknown API error"})
        self.assertEqual(runner.extract_api_errors([], ""), [])

    def test_api_error_is_saved_and_printed_even_when_validation_passes(self):
        event = {
            "type": "error",
            "error": {
                "name": "APIError",
                "data": {
                    "statusCode": 403,
                    "message": "Budget limit exceeded (weekly limit). custom-secret",
                    "responseBody": "Do not expose the raw response",
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            stream = io.StringIO()
            with (
                patch("runner.prepare", return_value=(output, output, "initial")),
                patch("runner.environment", return_value={}),
                patch("runner.Relay") as relay,
                patch("runner.collect_diff", return_value={}),
                patch("runner.sandbox", return_value=[]),
                patch("runner.probe"),
                patch(
                    "runner.execute",
                    side_effect=[
                        (1, 0.1, False, json.dumps(event).encode(), b""),
                        (0, 0.2, False, b"validation passed", b""),
                    ],
                ),
                patch("sys.stdout", stream),
            ):
                relay.return_value.server_port = 12345
                relay.return_value.snapshot.return_value = []
                metrics = runner.run_candidate(
                    "glm", fixture_archive(), output, "unused", "custom-secret"
                )
            saved = json.loads((output / "glm/metrics.json").read_text())
            self.assertEqual(saved["api_errors"], metrics["api_errors"])
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["validation"], "PASS")
            self.assertIn("API error 403: Budget limit exceeded (weekly limit).", stream.getvalue())
            for text in (json.dumps(saved), stream.getvalue()):
                self.assertNotIn("custom-secret", text)
                self.assertNotIn("Do not expose the raw response", text)

    def test_failure_and_timeout_still_validate(self):
        for timed_out in [False, True]:
            with self.subTest(timed_out=timed_out), tempfile.TemporaryDirectory() as temp:
                output = Path(temp)
                results = [
                    (1, 0.1, timed_out, b"", b"agent failed"),
                    (7, 0.2, False, b"validation ran", b"validation failure"),
                ]
                with (
                    patch("runner.sandbox", return_value=[]),
                    patch("runner.probe"),
                    patch("runner.execute", side_effect=results) as execute,
                ):
                    metrics = runner.run_candidate("glm", fixture_archive(), output, "unused", "")
                self.assertEqual(execute.call_count, 2)
                self.assertEqual(metrics["validation_exit_status"], 7)
                self.assertEqual(metrics["status"], "timed-out" if timed_out else "failed")
                self.assertIn("validation ran", (output / "glm/check.log").read_text())

    def test_all_continues_after_failure(self):
        scenario = runner.load_scenario()
        with tempfile.TemporaryDirectory() as temp:
            with (
                patch("runner.check_runtime", return_value="/fake/opencode"),
                patch("runner.ROOT", Path(temp)),
                patch("runner.load_scenario", return_value=scenario),
                patch("runner.command", return_value=runner.VERSION),
                patch(
                    "runner.run_candidate",
                    side_effect=[
                        {"model": a, "status": "failed", "validation": "FAIL"}
                        for a in runner.MODELS
                    ],
                ) as candidate,
            ):
                status = runner.main(["all", "--dry-run"])
            self.assertEqual(status, 1)
            self.assertEqual([c.args[0] for c in candidate.call_args_list], list(runner.MODELS))
            self.assertEqual(
                len(list(Path(temp).glob("results/field-notes/known-bug/*/runs/*"))),
                len(runner.MODELS),
            )


class FakeAPI(runner.http.server.BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *_args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(request)
        step = len(self.requests)
        delta = (
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "tool_fixture",
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps(
                                {
                                    "command": "printf 'regression\\n' > regression.txt",
                                    "description": "Create fixture regression file",
                                }
                            ),
                        },
                    }
                ]
            }
            if step == 1
            else {"content": "Fixture completed."}
        )
        base = {
            "id": f"gen-fixture-{step}",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": f"fixture/model-{step}",
            "provider": "FixtureProvider",
        }
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cost": 0.001,
            "prompt_tokens_details": {"cached_tokens": 2, "cache_write_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 1},
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for event in [
            dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
            dict(
                base,
                choices=[
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "tool_calls" if step == 1 else "stop",
                    }
                ],
                usage=usage,
            ),
        ]:
            self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


@unittest.skipUnless(os.environ.get("BENCHMARK_INTEGRATION") == "1", "opt-in sandbox integration")
class IntegrationTests(unittest.TestCase):
    def test_sandbox_blocks_metadata_results_and_other_workspaces(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            candidate = parent / "candidate"
            candidate.mkdir()
            workspace, home, _ = runner.prepare(fixture_archive(), candidate)
            other = parent / "other-candidate.txt"
            other.write_text("private")
            results = parent / "repo/results"
            results.mkdir(parents=True)
            result = results / "result.txt"
            result.write_text("previous result")
            source = results.parent / "source.py"
            source.write_text("private source")
            hidden = runner.ROOT / "scenarios/field-notes/evaluation/common.md"
            env = runner.environment(candidate, home, workspace)
            prefix = runner.sandbox(candidate, results)
            scenario = runner.ROOT / "scenarios/field-notes"
            private_paths = [
                *scenario.glob("evaluation/*.md"),
                *scenario.glob("tasks/*.md"),
                scenario / "checks/reproduce.test.ts",
                scenario / "scenario.toml",
            ]
            for path in [
                hidden,
                runner.ROOT / ".git/HEAD",
                runner.ROOT / "scripts/benchmark/runner.py",
                other,
                result,
                source,
                *private_paths,
            ]:
                output = runner.command(
                    prefix
                    + ["/bin/bash", "-c", 'test ! -r "$1" && printf blocked', "probe", str(path)],
                    workspace,
                    env,
                )
                self.assertEqual(output, "blocked")

    def test_identical_tool_sets_for_all_exact_models(self):
        api = runner.http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        exposed = []
        try:
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp)
                (output / "private-probe").write_text("invisible")
                for alias in runner.MODELS:
                    FakeAPI.requests = []
                    with patch("runner.TIMEOUT", 30):
                        metrics = runner.run_candidate(
                            alias,
                            fixture_archive(),
                            output,
                            shutil.which("opencode"),
                            "fixture-key",
                            upstream=f"http://127.0.0.1:{api.server_port}/api/v1",
                        )
                    self.assertEqual(metrics["status"], "completed", alias)
                    exposed.append(
                        {tool["function"]["name"] for tool in FakeAPI.requests[0]["tools"]}
                    )
                self.assertTrue(all(tools == exposed[0] for tools in exposed))
                self.assertIn("bash", exposed[0])
                self.assertFalse({"edit", "write", "apply_patch"} & exposed[0])
        finally:
            api.shutdown()
            api.server_close()
            thread.join()

    def test_real_opencode_with_fake_api_and_no_paid_calls(self):
        FakeAPI.requests = []
        api = runner.http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        thread = threading.Thread(target=api.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp)
                (output / "private-probe").write_text("invisible")
                with patch("runner.TIMEOUT", 90):
                    metrics = runner.run_candidate(
                        "glm",
                        fixture_archive(),
                        output,
                        shutil.which("opencode"),
                        "fixture-key",
                        upstream=f"http://127.0.0.1:{api.server_port}/api/v1",
                    )
                if metrics["status"] != "completed":
                    log = output / "glm/opencode.log"
                    print(log.read_text() if log.exists() else "No CLI stderr")
                    print((output / "glm/transcript.jsonl").read_text())
                self.assertEqual(metrics["status"], "completed")
                self.assertEqual(metrics["validation"], "PASS")
                self.assertEqual(metrics["actual_cost_usd"], 0.002)
                self.assertEqual(metrics["api_calls"], 2)
                self.assertEqual(metrics["input_tokens"], 20)
                self.assertEqual(metrics["changed_files"], 1)
                self.assertIn("regression.txt", (output / "glm/diff.patch").read_text())
                for request in FakeAPI.requests:
                    self.assertEqual(request["model"], runner.MODELS["glm"])
                    for field in ("reasoning", "reasoning_effort", "include_reasoning"):
                        self.assertNotIn(field, request)
                users = [m for m in FakeAPI.requests[0]["messages"] if m["role"] == "user"]
                content = users[0]["content"]
                text = (
                    content
                    if isinstance(content, str)
                    else "".join(part.get("text", "") for part in content)
                )
                self.assertEqual(text, runner.PROMPT)
        finally:
            api.shutdown()
            api.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
