import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

TEST_DATA = tempfile.TemporaryDirectory()
os.environ["YTDLP_GUI_DATA"] = TEST_DATA.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app, query_one  # noqa: E402


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_settings(self):
        response = self.client.put("/api/settings", json={
            "max_concurrent": 1, "fragments": 4})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/settings").json()["max_concurrent"], 1)

    def test_validations(self):
        self.assertEqual(self.client.post("/api/tasks", json={
            "url": "file:///etc/passwd", "split_mb": 500}).status_code, 400)
        self.assertEqual(self.client.post("/api/tasks", json={
            "url": "https://example.com/video", "split_mb": 1}).status_code, 422)

    def test_queue_and_cancel(self):
        response = self.client.post("/api/tasks", json={
            "url": "https://example.com/video", "split_mb": 500,
            "auto_split": False, "quality": "best"})
        self.assertEqual(response.status_code, 200)
        task = response.json()
        self.assertEqual(task["split_mb"], 500)
        self.assertEqual(query_one(task["id"])["status"], "queued")
        update = self.client.patch("/api/tasks/" + task["id"], json={"split_mb": 300})
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()["split_mb"], 300)
        cancel = self.client.post("/api/tasks/" + task["id"] + "/cancel")
        self.assertEqual(cancel.status_code, 200)
        self.assertEqual(cancel.json()["status"], "cancelled")
        retry = self.client.post("/api/tasks/" + task["id"] + "/retry")
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["status"], "queued")
        self.client.post("/api/tasks/" + task["id"] + "/cancel")


if __name__ == "__main__":
    unittest.main()
