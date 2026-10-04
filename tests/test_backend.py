"""Behavioral checks for saved reviews and the local HTTP boundary."""

import http.client
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path

from blackboard_workbench.adapter import demo, digest
from blackboard_workbench.jobs import Jobs
from blackboard_workbench.server import App, handler
from blackboard_workbench.store import Conflict, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "reviews.sqlite3")
        self.original = demo()
        self.run = self.store.import_run(self.original, "Synthetic coordinate mapping")
        self.lat = next(item for item in self.run["items"] if item["name"] == "lat")
        self.lon = next(item for item in self.run["items"] if item["name"] == "lon")

    def test_review_is_versioned_and_original_machine_output_is_unchanged(self):
        rid, iid = self.run["id"], self.lat["id"]
        cid = self.lat["candidates"][0]["id"]
        commented = self.store.event(rid, iid, {
            "author": "Reviewer A", "text": "Documentation supports latitude.",
            "version": 1, "references": [cid],
        })
        post = commented["events"][-1]
        self.assertEqual(1, next(i for i in commented["items"] if i["id"] == iid)["version"])
        decided = self.store.event(rid, iid, {
            "author": "Reviewer A", "text": "I accept the mapping.",
            "version": 1, "parent": post["id"], "references": [cid],
            "status": "accepted", "selected": cid,
        }, "decision")
        item = next(i for i in decided["items"] if i["id"] == iid)
        self.assertEqual((2, "accepted", cid), (item["version"], item["status"], item["selected"]))
        self.assertEqual(post["id"], decided["events"][-1]["parent"])
        self.assertEqual(self.original, decided["raw"])
        self.assertEqual(digest(self.original), decided["sha"])
        with self.assertRaises(Conflict):
            self.store.event(rid, iid, {
                "author": "Reviewer B", "text": "Old view", "version": 1,
                "status": "rejected",
            }, "decision")

    def test_invalid_candidate_and_cross_attribute_reply_are_rejected_without_changes(self):
        rid, iid = self.run["id"], self.lat["id"]
        with self.assertRaises(ValueError):
            self.store.event(rid, iid, {
                "author": "Reviewer", "text": "Bad candidate", "version": 1,
                "status": "accepted", "selected": "invented-candidate",
            }, "decision")
        lon_comment = self.store.event(rid, self.lon["id"], {
            "author": "Reviewer", "text": "Longitude note", "version": 1,
        })["events"][-1]
        with self.assertRaises(ValueError):
            self.store.event(rid, iid, {
                "author": "Reviewer", "text": "Wrong reply target",
                "version": 1, "parent": lon_comment["id"],
            })
        after = self.store.run(rid)
        self.assertEqual(1, len(after["events"]))
        self.assertEqual("unreviewed", next(i for i in after["items"] if i["id"] == iid)["status"])

    def test_reply_parent_must_be_a_post_identifier(self):
        rid, iid = self.run["id"], self.lat["id"]
        for bad_parent in ([], {}, 7, True):
            with self.subTest(parent=bad_parent):
                with self.assertRaises(ValueError):
                    self.store.event(rid, iid, {
                        "author": "Reviewer", "text": "Malformed reply",
                        "version": 1, "parent": bad_parent,
                    })
        self.assertFalse(self.store.run(rid)["events"])

    def test_agent_proposal_does_not_approve_and_rejects_stale_or_unknown_candidate(self):
        rid, iid = self.run["id"], self.lat["id"]
        cid = self.lat["candidates"][0]["id"]
        proposal = self.store.agent_event(rid, iid, {
            "author": "Mapping assessor", "text": "This candidate fits the documentation.",
            "version": 1, "proposed_candidate": cid,
        })
        item = next(i for i in proposal["items"] if i["id"] == iid)
        self.assertEqual(("unreviewed", None), (item["status"], item["selected"]))
        self.assertEqual("agent_response", proposal["events"][-1]["kind"])
        with self.assertRaises(ValueError):
            self.store.agent_event(rid, iid, {
                "author": "Mapping assessor", "text": "Unknown candidate",
                "version": 1, "proposed_candidate": "invented-candidate",
            })
        self.store.event(rid, iid, {
            "author": "Reviewer", "text": "Needs human review", "version": 1,
            "status": "needs_review",
        }, "decision")
        with self.assertRaises(Conflict):
            self.store.agent_event(rid, iid, {
                "author": "Mapping assessor", "text": "Stale proposal",
                "version": 1, "proposed_candidate": cid,
            })

    def test_concurrent_decisions_allow_only_one_version_to_commit(self):
        rid, iid = self.run["id"], self.lat["id"]
        barrier = threading.Barrier(2)

        def decide(name):
            barrier.wait(timeout=5)
            try:
                self.store.event(rid, iid, {
                    "author": name, "text": "Reviewed", "version": 1,
                    "status": "needs_review",
                }, "decision")
                return "committed"
            except Conflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(decide, ("A", "B")))
        self.assertCountEqual(("committed", "conflict"), outcomes)
        self.assertEqual(2, next(i for i in self.store.run(rid)["items"] if i["id"] == iid)["version"])


class JobRecoveryTests(unittest.TestCase):
    def test_early_filesystem_failure_releases_active_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = Store(root / "reviews.sqlite3")
            blocked_path = root / "file_instead_of_job_directory"
            blocked_path.write_text("not a directory")
            jobs = Jobs(store, blocked_path)
            jobs.active = "job-id"
            job = {"id": "job-id", "created": "2026-09-23T00:00:00+00:00"}
            jobs._execute(job, {})
            self.assertIsNone(jobs.active)
            self.assertEqual("failed", job["status"])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = App(self.temp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, payload=None, *, token=None, host=None, origin=None):
        port = self.server.server_port
        headers = {"Host": host or f"127.0.0.1:{port}"}
        if token is not None:
            headers["X-Workbench-Token"] = token
        if origin is not None:
            headers["Origin"] = origin
        body = json.dumps(payload).encode() if payload is not None else None
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, json.loads(data) if data else None
        finally:
            connection.close()

    def test_custom_upload_requires_token_and_saves_benchmark_choice(self):
        from test_datasets import payload
        _, config = self.request("GET", "/api/config")
        body = payload()
        self.assertEqual(403, self.request("POST", "/api/datasets", body)[0])
        status, inspected = self.request("POST", "/api/datasets/inspect", body, token=config["token"])
        self.assertEqual(200, status)
        self.assertEqual(["employee.name", "salary"], inspected["columns"])
        status, saved = self.request("POST", "/api/datasets", body, token=config["token"])
        self.assertEqual(201, status)
        self.assertFalse(saved["benchmark_available"])
        self.assertEqual([saved], self.request("GET", "/api/datasets")[1])
        self.assertNotIn("data", saved)
        status, error = self.request("POST", "/api/datasets", payload({}), token=config["token"])
        self.assertEqual(400, status)
        self.assertEqual(1, len(self.request("GET", "/api/datasets")[1]))

    def test_model_settings_require_token_and_never_return_credentials(self):
        _, config = self.request("GET", "/api/config")
        payload = {"provider": "openai", "model": "gpt-5", "api_key": "test-http-private-key"}
        self.assertEqual(403, self.request("POST", "/api/settings", payload)[0])
        status, settings = self.request("POST", "/api/settings", payload, token=config["token"])
        self.assertEqual(200, status)
        self.assertTrue(settings["has_key"])
        self.assertNotIn("test-http-private-key", json.dumps(settings))
        _, public = self.request("GET", "/api/config")
        self.assertNotIn("test-http-private-key", json.dumps(public))
        self.assertEqual(403, self.request("POST", "/api/settings/test", {})[0])
        self.assertEqual(403, self.request("POST", "/api/settings/models", {"provider": "local"})[0])

    def test_local_host_origin_and_token_are_required_for_writes(self):
        status, config = self.request("GET", "/api/config")
        self.assertEqual(200, status)
        self.assertTrue(config["token"])
        self.assertEqual(403, self.request("GET", "/api/config", host="attacker.example")[0])
        self.assertEqual(403, self.request("GET", "/api/config", origin="https://attacker.example")[0])
        self.assertEqual(403, self.request("POST", "/api/demo", {})[0])
        self.assertEqual(403, self.request("POST", "/api/demo", {}, token="wrong")[0])
        status, created = self.request("POST", "/api/demo", {}, token=config["token"])
        self.assertEqual(201, status)
        self.assertEqual("synthetic_demo", created["origin"])
        self.assertEqual(2, len(created["items"]))
        self.assertEqual(200, self.request("GET", f"/api/runs/{created['id']}")[0])


if __name__ == "__main__":
    unittest.main()
