import unittest
from datetime import datetime, timedelta, timezone

from skillpath import content, mastery, planning, recommender

TRACK = content.load_track("ai-ml")
NOW = datetime(2026, 10, 19, 22, 18, tzinfo=timezone.utc)


class MasteryTests(unittest.TestCase):
    def concept(self):
        return TRACK["concept_map"]["linear-models"]

    def test_empty_progress_scores_zero(self):
        m = mastery.concept_mastery(self.concept(), read=False, lc_status={}, answered=set(), applied=False)
        self.assertEqual(m["score"], 0)
        self.assertEqual(m["learning_score"], 0)

    def test_full_progress_scores_100(self):
        c = self.concept()
        lc = {link["n"]: "solved" for link in c["leetcode"]}
        answered = {q["id"] for q in c["industry"]}
        m = mastery.concept_mastery(c, read=True, lc_status=lc, answered=answered, applied=True)
        self.assertEqual(m["score"], 100)
        self.assertEqual(m["learning_score"], 100)

    def test_learning_score_ignores_applied(self):
        c = self.concept()
        lc = {link["n"]: "solved" for link in c["leetcode"]}
        answered = {q["id"] for q in c["industry"]}
        m = mastery.concept_mastery(c, read=True, lc_status=lc, answered=answered, applied=False)
        self.assertEqual(m["score"], 80)
        self.assertEqual(m["learning_score"], 100)

    def test_attempted_gives_partial_credit(self):
        c = self.concept()
        solved = mastery.concept_mastery(c, read=False, lc_status={c["leetcode"][0]["n"]: "solved"},
                                         answered=set(), applied=False)
        tried = mastery.concept_mastery(c, read=False, lc_status={c["leetcode"][0]["n"]: "attempted"},
                                        answered=set(), applied=False)
        self.assertGreater(solved["score"], tried["score"])
        self.assertGreater(tried["score"], 0)

    def test_applied_concepts_come_from_passed_projects(self):
        applied = mastery.applied_concepts(TRACK, ["linreg-scratch"])
        self.assertEqual(applied, set(TRACK["project_map"]["linreg-scratch"]["concepts"]))

    def test_project_readiness_is_average_learning_score(self):
        m = mastery.track_mastery(TRACK, read_ids={"python-numpy", "data-wrangling"}, lc_status={},
                                  answered=set(), passed_project_ids=[])
        self.assertEqual(mastery.project_readiness(TRACK["project_map"]["data-explorer"], m), 19)  # 15% of 80%


class RecommenderTests(unittest.TestCase):
    def test_new_user_starts_at_level_one(self):
        project, reason = recommender.recommend_next(TRACK, {})
        self.assertEqual(project["level"], 1)
        self.assertIn("beginning", reason)

    def test_prerequisites_are_enforced(self):
        ids = {p["id"] for p in recommender.eligible_projects(TRACK, {})}
        self.assertIn("data-explorer", ids)
        self.assertNotIn("logreg-eval", ids)  # needs linreg-scratch
        ids = {p["id"] for p in recommender.eligible_projects(TRACK, {"linreg-scratch": 80})}
        self.assertIn("logreg-eval", ids)

    def test_high_score_steps_up(self):
        passed = {"data-explorer": 95, "linreg-scratch": 95}
        steady, _ = recommender.recommend_next(TRACK, passed, last_score=80)
        stepped, reason = recommender.recommend_next(TRACK, passed, last_score=95)
        self.assertGreaterEqual(stepped["level"], steady["level"])
        self.assertEqual(steady["level"], 2)
        self.assertIn("95", reason)

    def test_step_up_never_skips_more_than_one_level(self):
        passed = {"data-explorer": 95, "linreg-scratch": 95}
        project, _ = recommender.recommend_next(TRACK, passed, last_score=95)
        self.assertLessEqual(project["level"], 2)

    def test_weak_concepts_break_ties(self):
        passed = {"data-explorer": 80, "linreg-scratch": 80}
        strong = mastery.track_mastery(TRACK, read_ids=set(), lc_status={}, answered=set(),
                                       passed_project_ids=[])
        # make classification/evaluation (logreg-eval) strong, nlp (spam-filter) weak
        for cid in ("classification", "evaluation", "linear-models"):
            strong[cid] = {**strong[cid], "score": 100}
        project, _ = recommender.recommend_next(TRACK, passed, last_score=80, mastery=strong)
        self.assertEqual(project["id"], "spam-filter")

    def test_finished_track_returns_none(self):
        everything = {p["id"]: 90 for p in TRACK["projects"]}
        project, reason = recommender.recommend_next(TRACK, everything, last_score=90)
        self.assertIsNone(project)
        self.assertIn("every project", reason)

    def test_locked_reasons_name_missing_prerequisites(self):
        project = TRACK["project_map"]["logreg-eval"]
        self.assertEqual(recommender.locked_reasons(TRACK, project, {}), ["Linear Regression from Scratch"])
        self.assertEqual(recommender.locked_reasons(TRACK, project, {"linreg-scratch": 70}), [])


class PlanningTests(unittest.TestCase):
    def test_schedule_covers_cycle_in_order(self):
        for weeks in (1, 2, 4, 12):
            due = NOW + timedelta(weeks=weeks)
            phases = planning.build_schedule(NOW, due)
            self.assertEqual([p["name"] for p in phases], ["Learn", "Build", "Polish", "Submit"])
            self.assertEqual(phases[0]["start"], NOW.date())
            self.assertEqual(phases[-1]["end"], due.date())
            for a, b in zip(phases, phases[1:]):
                self.assertLessEqual(a["start"], a["end"])
                self.assertEqual(b["start"], a["end"] + timedelta(days=1), f"gap/overlap at {weeks}w")

    def test_two_week_split_is_reasonable(self):
        phases = planning.build_schedule(NOW, NOW + timedelta(weeks=2))
        lengths = [(p["end"] - p["start"]).days + 1 for p in phases]
        self.assertGreaterEqual(lengths[1], lengths[0])  # building gets the most time
        self.assertGreaterEqual(min(lengths), 1)

    def test_sprint_quota_scales_with_cycle(self):
        self.assertEqual(planning.sprint_quota(2), 4)
        self.assertEqual(planning.sprint_quota(1), 2)
        self.assertEqual(planning.sprint_quota(6), 12)

    def test_sprint_skips_solved_and_is_unique(self):
        project = TRACK["project_map"]["logreg-eval"]
        first = planning.sprint_problems(TRACK, project, {}, 6)
        self.assertEqual(len({p["n"] for p in first}), len(first))
        self.assertEqual(len(first), 6)
        solved = {first[0]["n"]: "solved"}
        again = planning.sprint_problems(TRACK, project, solved, 6)
        self.assertNotIn(first[0]["n"], [p["n"] for p in again])

    def test_sprint_covers_each_concept_before_repeating(self):
        project = TRACK["project_map"]["logreg-eval"]
        picks = planning.sprint_problems(TRACK, project, {}, len(project["concepts"]))
        self.assertEqual({p["concept_id"] for p in picks}, set(project["concepts"]))

    def test_sprint_is_easiest_first_within_a_concept(self):
        project = TRACK["project_map"]["data-explorer"]
        picks = [p for p in planning.sprint_problems(TRACK, project, {}, 20) if p["concept_id"] == "data-wrangling"]
        ranks = [planning.DIFFICULTY_RANK[p["difficulty"]] for p in picks]
        self.assertEqual(ranks, sorted(ranks))


if __name__ == "__main__":
    unittest.main()
