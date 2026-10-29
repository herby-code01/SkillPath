import unittest

from skillpath import content


class ContentTests(unittest.TestCase):
    def test_every_track_validates(self):
        for track in content.list_tracks():
            with self.subTest(track=track["id"]):
                self.assertEqual(content.validate_track(track), [])

    def test_ai_ml_track_shape(self):
        track = content.load_track("ai-ml")
        self.assertEqual(len(track["concepts"]), 14)
        self.assertEqual(len(track["projects"]), 12)
        self.assertGreaterEqual(len(track["questions"]), 40)
        # every concept links to LeetCode problems and industry questions
        for c in track["concepts"]:
            self.assertGreaterEqual(len(c["leetcode"]), 4, c["id"])
            self.assertGreaterEqual(len(c["industry"]), 3, c["id"])

    def test_project_levels_are_ordered_with_prereqs(self):
        track = content.load_track("ai-ml")
        levels = [p["level"] for p in track["projects"]]
        self.assertEqual(levels, sorted(levels))

    def test_concept_problems_merges_catalog(self):
        track = content.load_track("ai-ml")
        problems = content.concept_problems(track, track["concept_map"]["python-numpy"])
        self.assertEqual(problems[0]["title"], "Reshape the Matrix")
        self.assertTrue(problems[0]["url"].startswith("https://leetcode.com/problems/"))

    def test_question_ids_are_unique_and_stable(self):
        track = content.load_track("ai-ml")
        self.assertIn("python-numpy-q1", track["questions"])
        self.assertEqual(track["questions"]["python-numpy-q1"]["concept_id"], "python-numpy")

    def test_validator_catches_problems(self):
        track = dict(content.load_track("ai-ml"))
        bad_projects = [dict(p) for p in track["projects"]]
        bad_projects[0]["concepts"] = ["does-not-exist"]
        bad_projects[1]["requires"] = ["data-explorer", "nope"]
        track["projects"] = bad_projects
        track["project_map"] = {p["id"]: p for p in bad_projects}
        errors = content.validate_track(track)
        self.assertTrue(any("unknown concept does-not-exist" in e for e in errors))
        self.assertTrue(any("unknown prerequisite nope" in e for e in errors))

    def test_validator_detects_prerequisite_cycle(self):
        track = dict(content.load_track("ai-ml"))
        projects = [dict(p) for p in track["projects"]]
        projects[0]["requires"] = ["linreg-scratch"]
        projects[1]["requires"] = ["data-explorer"]
        track["projects"] = projects
        track["project_map"] = {p["id"]: p for p in projects}
        self.assertTrue(any("cycle" in e for e in content.validate_track(track)))

    def test_unknown_track_raises(self):
        with self.assertRaises(KeyError):
            content.load_track("underwater-basket-weaving")


if __name__ == "__main__":
    unittest.main()
