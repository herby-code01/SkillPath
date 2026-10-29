import io
import json
import os
import unittest
import warnings
from datetime import timedelta

from skillpath.db import to_iso, utcnow

from .helpers import AppTestCase, make_zip
from .test_reviewer import GOOD_ZIP


class SubmissionFlowTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.register()
        self.client.post("/projects/data-explorer/start")
        self.aid = self.rows("SELECT id FROM assignments")[0]["id"]

    def rows(self, sql, args=()):
        with self.app.app_context():
            from skillpath.db import get_db
            return [dict(r) for r in get_db().execute(sql, args).fetchall()]

    def upload(self, name, data, aid=None, **kw):
        return self.client.post(f"/assignments/{aid or self.aid}/submit",
                                data={"file": (io.BytesIO(data), name)}, follow_redirects=kw.pop("follow", True), **kw)

    def test_passing_submission_closes_cycle_and_recommends_next(self):
        res = self.upload("p.zip", make_zip(GOOD_ZIP))
        self.assertIn(b"Passed", res.data)
        self.assertIn(b"Next up", res.data)
        a = self.rows("SELECT * FROM assignments")[0]
        self.assertEqual(a["status"], "passed")
        self.assertGreaterEqual(a["best_score"], 70)
        self.assertIsNotNone(a["completed_at"])
        sub = self.rows("SELECT * FROM submissions")[0]
        self.assertEqual(sub["passed"], 1)
        self.assertEqual(json.loads(sub["report_json"])["score"], sub["score"])

    def test_after_passing_user_can_start_the_next_project(self):
        self.upload("p.zip", make_zip(GOOD_ZIP))
        self.assertIn(b"Your next project", self.client.get("/dashboard").data)
        self.client.post("/projects/linreg-scratch/start")
        self.assertEqual(len(self.rows("SELECT * FROM assignments")), 2)

    def test_failing_submission_needs_revision_and_can_resubmit(self):
        res = self.upload("bad.py", b"print('hi')\n")
        self.assertIn(b"Not a pass yet", res.data)
        self.assertIn(b"Biggest improvements", res.data)
        a = self.rows("SELECT * FROM assignments")[0]
        self.assertEqual(a["status"], "needs_revision")
        dash = self.client.get("/dashboard").data
        self.assertIn(b"Needs revision", dash)
        self.assertIn(b"bad.py", dash)  # attempts list
        self.upload("p.zip", make_zip(GOOD_ZIP))
        self.assertEqual(self.rows("SELECT status FROM assignments")[0]["status"], "passed")
        self.assertEqual(len(self.rows("SELECT * FROM submissions")), 2)

    def test_best_score_on_pass_is_the_passing_score_not_an_earlier_higher_failure(self):
        files = dict(GOOD_ZIP)
        files["explorer/config.py"] = 'API_KEY = "abcd1234efgh5678ijkl9012"\n'  # gate: cannot pass
        self.upload("secret.zip", make_zip(files))
        first = self.rows("SELECT * FROM submissions")[0]
        self.assertEqual(first["passed"], 0)
        self.upload("clean.zip", make_zip(GOOD_ZIP))
        a = self.rows("SELECT * FROM assignments")[0]
        last = self.rows("SELECT * FROM submissions ORDER BY id DESC")[0]
        self.assertEqual(a["status"], "passed")
        self.assertEqual(a["best_score"], last["score"])

    def test_late_submission_is_flagged_and_penalized(self):
        with self.app.app_context():
            from skillpath.db import get_db
            db = get_db()
            db.execute("UPDATE assignments SET due_at = ? WHERE id = ?", (to_iso(utcnow() - timedelta(days=1)), self.aid))
            db.commit()
        self.upload("p.zip", make_zip(GOOD_ZIP))
        sub = self.rows("SELECT * FROM submissions")[0]
        self.assertEqual(sub["late"], 1)
        self.assertTrue(json.loads(sub["report_json"])["late"])

    def test_bad_uploads_are_rejected_without_recording(self):
        for name, data in (("notes.txt", b"hello"), ("empty.py", b""), ("broken.zip", b"not a zip")):
            res = self.upload(name, data)
            self.assertEqual(res.status_code, 200)
        self.assertEqual(self.rows("SELECT * FROM submissions"), [])
        self.assertEqual(self.rows("SELECT status FROM assignments")[0]["status"], "active")

    def test_missing_file_field(self):
        res = self.client.post(f"/assignments/{self.aid}/submit", data={}, follow_redirects=True)
        self.assertIn(b"Choose a .zip", res.data)

    def test_oversized_upload_returns_413_page(self):
        with warnings.catch_warnings():
            # Werkzeug leaves its own spooled temp file open when it rejects an oversized body
            warnings.simplefilter("ignore", ResourceWarning)
            res = self.upload("big.zip", b"0" * (5 * 1024 * 1024 + 10), follow=False)
        self.assertEqual(res.status_code, 413)

    def test_upload_is_stored_under_users_folder_with_safe_name(self):
        self.upload("../../evil name.py", b"x = 1\n")
        sub = self.rows("SELECT * FROM submissions")[0]
        self.assertNotIn("..", sub["stored_path"])
        self.assertNotIn("evil name", sub["stored_path"])
        self.assertTrue(os.path.exists(os.path.join(self.app.config["UPLOAD_DIR"], sub["stored_path"])))
        self.assertEqual(sub["filename"], "evil_name.py")

    def test_cannot_submit_to_closed_or_foreign_assignment(self):
        self.upload("p.zip", make_zip(GOOD_ZIP))  # passes, closes the cycle
        res = self.upload("p.zip", make_zip(GOOD_ZIP))
        self.assertIn(b"already closed", res.data)
        self.assertEqual(len(self.rows("SELECT * FROM submissions")), 1)
        self.logout()
        self.register("mallory")
        self.assertEqual(self.upload("p.zip", make_zip(GOOD_ZIP), follow=False).status_code, 404)

    def test_report_is_private_to_its_owner(self):
        self.upload("p.zip", make_zip(GOOD_ZIP))
        sid = self.rows("SELECT id FROM submissions")[0]["id"]
        self.assertEqual(self.client.get(f"/submissions/{sid}").status_code, 200)
        self.logout()
        self.register("mallory")
        self.assertEqual(self.client.get(f"/submissions/{sid}").status_code, 404)
        self.assertEqual(self.client.get("/submissions/9999").status_code, 404)

    def test_report_page_shows_categories_and_limitations(self):
        self.upload("p.zip", make_zip(GOOD_ZIP))
        sid = self.rows("SELECT id FROM submissions")[0]["id"]
        html = self.client.get(f"/submissions/{sid}").data
        for word in (b"Requirements", b"Code quality", b"Tests", b"Documentation", b"Packaging",
                     b"never runs your code"):
            self.assertIn(word, html)

    def test_report_html_escapes_filenames_from_the_zip(self):
        files = {"<script>alert(1)</script>.py": "x = 1\n"}
        self.upload("p.zip", make_zip(files))
        sid = self.rows("SELECT id FROM submissions")[0]["id"]
        html = self.client.get(f"/submissions/{sid}").data
        self.assertNotIn(b"<script>alert(1)</script>", html)


if __name__ == "__main__":
    unittest.main()
