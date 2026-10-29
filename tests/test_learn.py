import unittest

from skillpath import content

from .helpers import AppTestCase

TRACK = content.load_track("ai-ml")


class LearnTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.register()

    def rows(self, sql, args=()):
        with self.app.app_context():
            from skillpath.db import get_db
            return [dict(r) for r in get_db().execute(sql, args).fetchall()]

    def mastery(self, cid):
        with self.app.app_context():
            from skillpath.db import get_db
            from skillpath.progress import load_state
            user = get_db().execute("SELECT * FROM users").fetchone()
            return load_state(get_db(), user)[2][cid]

    def test_login_required(self):
        self.logout()
        for path in ("/learn", "/learn/python-numpy", "/leetcode"):
            self.assertEqual(self.client.get(path).status_code, 302, path)
        for path in ("/learn/python-numpy/read", "/leetcode/1/status", "/questions/python-numpy-q1/answer"):
            self.assertEqual(self.client.post(path).status_code, 302, path)

    def test_every_concept_page_renders(self):
        self.assertEqual(self.client.get("/learn").status_code, 200)
        for c in TRACK["concepts"]:
            res = self.client.get(f"/learn/{c['id']}")
            self.assertEqual(res.status_code, 200, c["id"])
            self.assertIn(c["title"].encode().replace(b"&", b"&amp;"), res.data)
        self.assertEqual(self.client.get("/learn/nope").status_code, 404)

    def test_mark_read_and_undo(self):
        self.client.post("/learn/python-numpy/read", data={"read": "1"})
        self.assertEqual(self.mastery("python-numpy")["score"], 15)
        self.client.post("/learn/python-numpy/read", data={"read": "1"})  # idempotent
        self.assertEqual(len(self.rows("SELECT * FROM concept_progress")), 1)
        self.client.post("/learn/python-numpy/read", data={"read": "0"})
        self.assertEqual(self.mastery("python-numpy")["score"], 0)

    def test_mark_read_unknown_concept(self):
        self.assertEqual(self.client.post("/learn/nope/read").status_code, 404)

    def test_leetcode_status_updates_mastery_and_can_change(self):
        first = TRACK["concept_map"]["python-numpy"]["leetcode"][0]["n"]
        self.client.post(f"/leetcode/{first}/status", data={"status": "attempted"})
        attempted = self.mastery("python-numpy")["score"]
        self.client.post(f"/leetcode/{first}/status", data={"status": "solved"})
        solved = self.mastery("python-numpy")["score"]
        self.assertGreater(attempted, 0)
        self.assertGreater(solved, attempted)
        self.assertEqual(len(self.rows("SELECT * FROM lc_progress")), 1)  # upsert, not duplicate
        self.client.post(f"/leetcode/{first}/status", data={"status": "todo"})
        self.assertEqual(self.rows("SELECT * FROM lc_progress"), [])
        self.assertEqual(self.mastery("python-numpy")["score"], 0)

    def test_leetcode_status_validation(self):
        self.assertEqual(self.client.post("/leetcode/1/status", data={"status": "mastered"}).status_code, 400)
        self.assertEqual(self.client.post("/leetcode/999999/status", data={"status": "solved"}).status_code, 400)
        self.assertEqual(self.client.post("/leetcode/1/status", data={}).status_code, 400)
        self.assertEqual(self.rows("SELECT * FROM lc_progress"), [])

    def test_leetcode_status_redirect_is_safe(self):
        res = self.client.post("/leetcode/1/status", data={"status": "solved", "next": "https://evil.example/x"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.headers["Location"].endswith("/leetcode"))
        res = self.client.post("/leetcode/1/status", data={"status": "solved", "next": "//evil.example"})
        self.assertTrue(res.headers["Location"].endswith("/leetcode"))
        res = self.client.post("/leetcode/1/status", data={"status": "solved", "next": "/learn/python-numpy"})
        self.assertTrue(res.headers["Location"].endswith("/learn/python-numpy"))

    def test_leetcode_page_filters(self):
        self.client.post("/leetcode/1/status", data={"status": "solved"})
        everything = self.client.get("/leetcode").data
        solved_only = self.client.get("/leetcode?status=solved").data
        hard_only = self.client.get("/leetcode?difficulty=Hard").data
        self.assertIn(b"Two Sum", everything)
        self.assertIn(b"Two Sum", solved_only)
        self.assertNotIn(b"Merge Intervals", solved_only)
        self.assertNotIn(b"Two Sum", hard_only)
        self.assertIn(b"Merge k Sorted Lists", hard_only)
        self.assertIn(b"No problems match", self.client.get("/leetcode?status=attempted&difficulty=Hard").data)

    def test_answer_needs_real_effort_then_counts(self):
        qid = "python-numpy-q1"
        res = self.client.post(f"/questions/{qid}/answer", data={"answer": "idk"}, follow_redirects=True)
        self.assertIn(b"Write at least", res.data)
        self.assertEqual(self.rows("SELECT * FROM industry_progress"), [])
        self.assertNotIn(b"What a strong answer covers", res.data)

        text = "Broadcast the arrays with new axes and use the dot-product expansion to avoid loops."
        res = self.client.post(f"/questions/{qid}/answer", data={"answer": text}, follow_redirects=True)
        self.assertIn(b"Answer saved", res.data)
        self.assertIn(b"What a strong answer covers", res.data)  # key points revealed only after answering
        self.assertGreater(self.mastery("python-numpy")["score"], 0)

        self.client.post(f"/questions/{qid}/answer", data={"answer": text + " Edited."})
        self.assertEqual(len(self.rows("SELECT * FROM industry_progress")), 1)

    def test_answer_unknown_question_and_length_cap(self):
        self.assertEqual(self.client.post("/questions/nope/answer", data={"answer": "x" * 50}).status_code, 404)
        self.client.post("/questions/python-numpy-q1/answer", data={"answer": "y" * 9000})
        self.assertEqual(len(self.rows("SELECT answer FROM industry_progress")[0]["answer"]), 4000)

    def test_answers_are_html_escaped(self):
        self.client.post("/questions/python-numpy-q1/answer", data={"answer": "<script>alert(1)</script> padding text here"})
        html = self.client.get("/learn/python-numpy").data
        self.assertNotIn(b"<script>alert(1)</script>", html)
        self.assertIn(b"&lt;script&gt;", html)

    def test_progress_is_per_user(self):
        self.client.post("/leetcode/1/status", data={"status": "solved"})
        self.client.post("/learn/python-numpy/read", data={"read": "1"})
        self.logout()
        self.register("other")
        self.assertNotIn(b"aria-pressed=\"true\">Solved", self.client.get("/leetcode").data)
        self.assertEqual(self.client.get("/learn/python-numpy").status_code, 200)
        self.assertIn(b"Mark primer as read", self.client.get("/learn/python-numpy").data)

    def test_studying_raises_dashboard_readiness_and_project_page_links_to_primers(self):
        for cid in ("python-numpy", "data-wrangling"):
            self.client.post(f"/learn/{cid}/read", data={"read": "1"})
        html = self.client.get("/projects/data-explorer").data
        self.assertIn(b"/learn/python-numpy", html)
        self.assertIn(b"Readiness for this project: <strong>19%</strong>", html)

    def test_finishing_practice_shifts_recommendation_toward_weak_areas(self):
        # Pass the two level-1 projects so level 2 is open, then master the logistic-regression concepts.
        with self.app.app_context():
            from skillpath.db import get_db, to_iso, utcnow
            db = get_db()
            uid = db.execute("SELECT id FROM users").fetchone()["id"]
            for pid in ("data-explorer", "linreg-scratch"):
                db.execute("INSERT INTO assignments (user_id, project_id, status, cycle_weeks, started_at, due_at, "
                           "completed_at, best_score) VALUES (?, ?, 'passed', 2, ?, ?, ?, 80)",
                           (uid, pid, to_iso(utcnow()), to_iso(utcnow()), to_iso(utcnow())))
            db.commit()
        before = self.client.get("/dashboard").data
        self.assertIn(b"Logistic Regression", before)  # first eligible, nothing studied yet
        for cid in ("classification", "evaluation", "linear-models"):
            for link in TRACK["concept_map"][cid]["leetcode"]:
                self.client.post(f"/leetcode/{link['n']}/status", data={"status": "solved"})
            self.client.post(f"/learn/{cid}/read", data={"read": "1"})
            for q in TRACK["concept_map"][cid]["industry"]:
                self.client.post(f"/questions/{q['id']}/answer", data={"answer": "A thorough written explanation here."})
        after = self.client.get("/dashboard").data
        self.assertIn(b"Naive Bayes Spam Filter", after)  # recommender now targets the weaker concepts


if __name__ == "__main__":
    unittest.main()
