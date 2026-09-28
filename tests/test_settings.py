import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from blackboard_workbench.settings import ModelSettings, validate_endpoint
from blackboard_workbench.jobs import Jobs
from blackboard_workbench.store import Store


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = ModelSettings(self.root, environ={})

    def save(self, **extra):
        return self.settings.save({"provider": "openai", "model": "gpt-5", "api_key": "test-private-credential", **extra})

    def test_session_key_never_enters_public_config_or_files_and_expires(self):
        result = self.save()
        self.assertTrue(result["ready"])
        self.assertEqual("session", result["key_source"])
        self.assertNotIn("test-private-credential", json.dumps(result))
        for file in self.root.glob("*.json"):
            self.assertNotIn("test-private-credential", file.read_text())
        self.assertFalse(ModelSettings(self.root, environ={}).public()["ready"])
        self.assertEqual("test-private-credential", self.settings.resolve()["api_key"])

    def test_remembered_key_is_protected_persists_and_can_be_removed(self):
        self.save(remember_key=True)
        path = self.root / "credentials.json"
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        reopened = ModelSettings(self.root, environ={})
        self.assertEqual("saved", reopened.public()["key_source"])
        reopened.save({"provider": "openai", "model": "gpt-5", "clear_key": True})
        self.assertNotIn("test-private-credential", path.read_text())
        self.assertFalse(reopened.public()["ready"])

    def test_storage_checkbox_can_move_existing_key_between_session_and_file(self):
        self.save()
        payload = {"provider": "openai", "model": "gpt-5", "api_key": "", "remember_key": True}
        self.settings.save(payload)
        self.assertEqual("saved", self.settings.public()["key_source"])
        self.assertTrue(ModelSettings(self.root, environ={}).public()["has_key"])
        self.settings.save({**payload, "remember_key": False})
        self.assertEqual("session", self.settings.public()["key_source"])
        self.assertNotIn("test-private-credential", (self.root / "credentials.json").read_text())
        self.assertFalse(ModelSettings(self.root, environ={}).public()["has_key"])
        self.assertEqual("test-private-credential", self.settings.resolve()["api_key"])

    def test_checkbox_never_copies_environment_key_to_saved_file(self):
        settings = ModelSettings(self.root, environ={"OPENAI_API_KEY": "environment-secret"})
        settings.save({"provider": "openai", "model": "gpt-5", "remember_key": True})
        self.assertEqual("environment", settings.public()["key_source"])
        for file in self.root.glob("*.json"):
            self.assertNotIn("environment-secret", file.read_text())

    def test_empty_key_preserves_existing_key_and_profiles_remain_separate(self):
        self.save()
        self.settings.save({"provider": "openai", "model": "gpt-5-mini", "api_key": ""})
        self.settings.save({"provider": "ollama", "model": "installed-local-model"})
        self.assertTrue(self.settings.public()["ready"])
        self.assertFalse(self.settings.public()["has_key"])
        self.assertEqual("test-private-credential", self.settings.resolve(provider="openai")["api_key"])
        self.assertEqual("gpt-5-mini", self.settings.resolve(provider="openai")["model"])
        self.assertFalse(self.settings.public()["profiles"]["anthropic"]["ready"])

    def test_environment_fallback_not_returned_and_redaction_covers_all_providers(self):
        settings = ModelSettings(self.root, environ={"ANTHROPIC_API_KEY": "claude-secret", "OPENAI_API_KEY": "openai-secret"})
        self.assertEqual("environment", settings.public()["key_source"])
        self.assertNotIn("openai-secret", json.dumps(settings.public()))
        self.assertEqual("[redacted key] [redacted key] [redacted key]", settings.redacted("claude-secret openai-secret removed-secret", ("removed-secret",)))

    def test_cloud_endpoint_cannot_redirect_a_key_and_local_url_is_restricted(self):
        with self.assertRaises(ValueError):
            validate_endpoint("openai", "https://other.example/v1")
        for url in ("http://public.example/v1", "http://169.254.169.254/v1", "http://user:pass@localhost:1234/v1", "http://localhost:1234/v1?key=x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_endpoint("local", url)
        self.assertEqual("http://192.168.1.5:8000/v1", validate_endpoint("local", "http://192.168.1.5:8000/v1/"))

    def test_short_model_test_requires_json_and_never_returns_key(self):
        self.save()
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
        with patch("blackboard_workbench.llm.make_client", return_value=client):
            self.assertTrue(self.settings.test()["ok"])
            response.choices[0].message.content = "```json\n{}\n```"
            with self.assertRaisesRegex(ValueError, "requested JSON"):
                self.settings.test()


class JobCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        entry = self.source / "blackboard/codebase/core/blackboard_semantic_mapping.py"
        entry.parent.mkdir(parents=True)
        entry.write_text("")
        sample = self.source / "datacorpus/vcslam/0044"
        sample.mkdir(parents=True)
        (sample / "0044_samples.json").write_text("{}")
        self.settings = ModelSettings(self.root / "data", environ={})
        self.store = Store(self.root / "data/store.sqlite3")
        self.jobs = Jobs(self.store, self.root / "data", self.source, "python", self.settings)

    def test_missing_key_rejected_before_job_is_saved(self):
        with self.assertRaisesRegex(ValueError, "API key"):
            self.jobs.start({"kind": "pipeline", "samples": ["0044"]})
        self.assertEqual([], self.store.jobs())
        self.assertIsNone(self.jobs.active)

    def test_job_config_and_history_exclude_key_and_snapshot_separate_credential(self):
        secret = "snapshot-private-key"
        self.settings.save({"provider": "anthropic", "model": "claude-model", "api_key": secret})
        with patch("blackboard_workbench.jobs.threading.Thread") as thread:
            job = self.jobs.start({"kind": "pipeline", "samples": ["0044"]})
        job_arg, config_arg, private_arg = thread.call_args.kwargs["args"]
        self.assertEqual("anthropic", job["provider"])
        self.assertNotIn(secret, json.dumps(job))
        self.assertNotIn(secret, json.dumps(config_arg))
        self.assertNotIn(secret, json.dumps(self.store.jobs()))
        self.assertEqual(secret, private_arg["api_key"])
        self.settings.save({"provider": "anthropic", "model": "claude-model", "clear_key": True})
        log = self.root / "log"
        log.write_text("provider logged " + secret)
        self.assertNotIn(secret, self.jobs._log(log, (private_arg["api_key"],)))


    def test_cancelled_worker_exit_is_not_recorded_as_failure(self):
        self.settings.save({"provider": "ollama", "model": "local-model"})
        with patch("blackboard_workbench.jobs.threading.Thread") as thread:
            job = self.jobs.start({"kind": "pipeline", "samples": ["0044"]})
        args = thread.call_args.kwargs["args"]
        self.jobs.cancelled.add(job["id"])
        process = Mock(returncode=-15)
        process.poll.return_value = -15
        with patch("blackboard_workbench.jobs.subprocess.Popen", return_value=process):
            self.jobs._execute(*args)
        self.assertEqual("cancelled", self.store.jobs()[0]["status"])
        self.assertIsNone(self.jobs.active)


if __name__ == "__main__":
    unittest.main()
