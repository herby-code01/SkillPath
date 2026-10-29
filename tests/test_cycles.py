import unittest
from datetime import timedelta

from skillpath.db import from_iso, to_iso, utcnow

from .helpers import AppTestCase


class CycleFlowTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.register()

    def db_rows(self, sql, args=()):
        with self.app.app_context():
            from skillpath.db import get_db
            return [dict(r) for r in get_db().execute(sql, args).fetchall()]

    def db_exec(self, sql, args=()):
        with self.app.app_context():
            from skillpath.db import get_db
            db = get_db()
            db.execute(sql, args)
            db.commit()

    def test_pages_require_login(self):
        self.logout()
        for path in ("/dashboard", "/roadmap", "/settings", "/projects/data-explorer"):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302, path)
            self.assertIn("/login", res.headers["Location"])

    def test_home_redirects_logged_in_user_to_dashboard(self):
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_new_user_dashboard_recommends_first_project(self):
        res = self.client.get("/dashboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Your next project", res.data)
        self.assertIn(b"Start a 2-week cycle", res.data)

    def test_roadmap_shows_all_levels_and_locks(self):
        res = self.client.get("/roadmap")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Foundations", res.data)
        self.assertIn(b"Locked", res.data)
        self.assertIn(b"Tiny GPT", res.data)

    def test_every_project_page_renders(self):
        from skillpath import content
        for p in content.load_track("ai-ml")["projects"]:
            res = self.client.get(f"/projects/{p['id']}")
            self.assertEqual(res.status_code, 200, p["id"])
        self.assertEqual(self.client.get("/projects/nope").status_code, 404)

    def test_start_uses_cycle_weeks_setting(self):
        self.client.post("/settings", data={"cycle_weeks": "3", "track_id": "ai-ml"})
        self.client.post("/projects/data-explorer/start")
        row = self.db_rows("SELECT * FROM assignments")[0]
        self.assertEqual(row["cycle_weeks"], 3)
        days = (from_iso(row["due_at"]) - from_iso(row["started_at"])).days
        self.assertEqual(days, 21)

    def test_default_cycle_is_two_weeks(self):
        self.client.post("/projects/data-explorer/start")
        row = self.db_rows("SELECT * FROM assignments")[0]
        self.assertEqual((from_iso(row["due_at"]) - from_iso(row["started_at"])).days, 14)

    def test_cannot_start_locked_project(self):
        res = self.client.post("/projects/logreg-eval/start", follow_redirects=True)
        self.assertIn(b"Pass these first", res.data)
        self.assertEqual(self.db_rows("SELECT * FROM assignments"), [])

    def test_only_one_open_project_at_a_time(self):
        self.client.post("/projects/data-explorer/start")
        res = self.client.post("/projects/linreg-scratch/start", follow_redirects=True)
        self.assertIn(b"Finish or abandon", res.data)
        self.assertEqual(len(self.db_rows("SELECT * FROM assignments")), 1)

    def test_active_dashboard_shows_plan_and_sprint(self):
        self.client.post("/projects/data-explorer/start")
        res = self.client.get("/dashboard")
        self.assertIn(b"Current project", res.data)
        self.assertIn(b"Cycle plan", res.data)
        self.assertIn(b"LeetCode sprint", res.data)
        self.assertIn(b"leetcode.com/problems/", res.data)

    def test_extend_pushes_due_date_and_counts(self):
        self.client.post("/projects/data-explorer/start")
        before = self.db_rows("SELECT * FROM assignments")[0]
        self.client.post(f"/assignments/{before['id']}/extend")
        after = self.db_rows("SELECT * FROM assignments")[0]
        self.assertEqual(after["extended_count"], 1)
        self.assertEqual(from_iso(after["due_at"]) - from_iso(before["due_at"]), timedelta(weeks=2))

    def test_overdue_extension_counts_from_now(self):
        self.client.post("/projects/data-explorer/start")
        a = self.db_rows("SELECT * FROM assignments")[0]
        self.db_exec("UPDATE assignments SET due_at = ? WHERE id = ?",
                     (to_iso(utcnow() - timedelta(days=10)), a["id"]))
        self.client.post(f"/assignments/{a['id']}/extend")
        due = from_iso(self.db_rows("SELECT * FROM assignments")[0]["due_at"])
        self.assertGreater(due, utcnow() + timedelta(days=13))

    def test_abandon_frees_the_slot(self):
        self.client.post("/projects/data-explorer/start")
        a = self.db_rows("SELECT * FROM assignments")[0]
        self.client.post(f"/assignments/{a['id']}/abandon")
        self.assertEqual(self.db_rows("SELECT status FROM assignments")[0]["status"], "abandoned")
        self.client.post("/projects/linreg-scratch/start")
        self.assertEqual(len(self.db_rows("SELECT * FROM assignments")), 2)

    def test_cannot_touch_another_users_assignment(self):
        self.client.post("/projects/data-explorer/start")
        a = self.db_rows("SELECT * FROM assignments")[0]
        self.logout()
        self.register("mallory")
        self.assertEqual(self.client.post(f"/assignments/{a['id']}/abandon").status_code, 404)
        self.assertEqual(self.client.post(f"/assignments/{a['id']}/extend").status_code, 404)
        self.assertEqual(self.db_rows("SELECT status FROM assignments")[0]["status"], "active")

    def test_settings_validation(self):
        for bad in ("0", "13", "abc", ""):
            res = self.client.post("/settings", data={"cycle_weeks": bad, "track_id": "ai-ml"})
            self.assertIn(b"Cycle length must be", res.data, bad)
        res = self.client.post("/settings", data={"cycle_weeks": "4", "track_id": "bogus"})
        self.assertIn(b"Unknown track", res.data)
        self.client.post("/settings", data={"cycle_weeks": "4", "track_id": "ai-ml"})
        self.assertEqual(self.db_rows("SELECT cycle_weeks FROM users")[0]["cycle_weeks"], 4)

    def test_changing_weeks_does_not_alter_open_cycle(self):
        self.client.post("/projects/data-explorer/start")
        self.client.post("/settings", data={"cycle_weeks": "6", "track_id": "ai-ml"})
        self.assertEqual(self.db_rows("SELECT cycle_weeks FROM assignments")[0]["cycle_weeks"], 2)

    def test_timezone_cookie_shifts_displayed_dates(self):
        self.client.post("/projects/data-explorer/start")
        utc = self.client.get("/dashboard").data
        self.client.set_cookie("tzo", "720")  # UTC-12
        shifted = self.client.get("/dashboard").data
        self.assertNotEqual(utc, shifted)


if __name__ == "__main__":
    unittest.main()
