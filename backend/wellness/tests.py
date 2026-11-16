from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from billing.models import CommissionRate
from venues.models import Sport
from wellness.management.commands import seed
from wellness.models import BodyArea, Exercise, ExerciseBodyArea


def counts():
    return (Sport.objects.count(), CommissionRate.objects.count(), Exercise.objects.count(), ExerciseBodyArea.objects.count())


class SeedTests(TestCase):
    def test_first_run_creates_everything(self):
        """SEED-1, SEED-2, SEED-3: first run creates the sports, default commissions and placeholder exercises."""
        call_command("seed")
        self.assertEqual(
            set(Sport.objects.values_list("name", flat=True)),
            {"Padel", "Tennis", "Basketball", "Volleyball", "Football (5-a-side)", "Pickleball", "Squash", "Badminton"},
        )
        self.assertEqual(Sport.objects.count(), 8)
        self.assertEqual(CommissionRate.objects.count(), 2)
        for applies_to in ("club", "coach"):
            rate = CommissionRate.objects.get(applies_to=applies_to)
            self.assertIsNone(rate.club_id)
            self.assertIsNone(rate.coach_id)
            self.assertEqual(str(rate.percent), "10.00")
            self.assertEqual(rate.min_count, 0)
            self.assertEqual(rate.effective_from, timezone.now().date())
        self.assertEqual(len(seed.EXERCISES), 24)
        self.assertEqual(Exercise.objects.count(), 24)
        for name, kind, areas, low, high in seed.EXERCISES:
            ex = Exercise.objects.get(name=name)
            self.assertEqual((ex.kind, ex.min_soreness, ex.max_soreness), (kind, low, high))
            self.assertTrue(ex.description.startswith("Placeholder, to be reviewed by the sports expert."))
            self.assertEqual(ex.video_url, "")
            self.assertEqual(set(ex.body_areas.values_list("body_area", flat=True)), set(areas))
        child = Exercise.objects.get(name="Child's pose")
        self.assertEqual((child.kind, child.max_soreness), ("stretch", 8))

    def test_second_run_changes_nothing(self):
        """SEED-1, SEED-2, SEED-3: running again creates no rows."""
        call_command("seed")
        before = counts()
        call_command("seed")
        self.assertEqual(counts(), before)

    def test_rerun_keeps_admin_edits_and_recreates_deleted_sport(self):
        """SEED-1, SEED-2, SEED-3, COM-4: admin edits survive a re-run; a deleted sport comes back."""
        call_command("seed")
        ex = Exercise.objects.get(name="Child's pose")
        ex.max_soreness = 5
        ex.save()
        ex.body_areas.filter(body_area="hips").delete()
        rate = CommissionRate.objects.get(applies_to="club")
        rate.percent = "12.50"
        rate.save()
        Sport.objects.get(name="Squash").delete()

        call_command("seed")

        ex.refresh_from_db()
        self.assertEqual(ex.max_soreness, 5)
        self.assertEqual(list(ex.body_areas.values_list("body_area", flat=True)), ["lower_back"])
        self.assertEqual(CommissionRate.objects.filter(applies_to="club").count(), 1)
        rate.refresh_from_db()
        self.assertEqual(str(rate.percent), "12.50")
        self.assertTrue(Sport.objects.filter(name="Squash").exists())

    def test_every_body_area_has_an_exercise(self):
        """SEED-3: all 16 body areas are covered."""
        call_command("seed")
        self.assertEqual(len(BodyArea.values), 16)
        covered = set(ExerciseBodyArea.objects.values_list("body_area", flat=True))
        self.assertEqual(covered, set(BodyArea.values))
