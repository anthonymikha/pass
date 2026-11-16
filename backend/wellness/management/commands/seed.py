"""Seed data: SEED-1 (sports), SEED-2 (default commission), SEED-3 (placeholder exercises).

Safe to run again: never duplicates rows and never overwrites rows an admin has edited.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from billing.models import CommissionRate
from venues.models import Sport
from wellness.models import Exercise, ExerciseBodyArea

# SEED-1
SPORTS = ["Padel", "Tennis", "Basketball", "Volleyball", "Football (5-a-side)", "Pickleball", "Squash", "Badminton"]

PLACEHOLDER = "Placeholder, to be reviewed by the sports expert."

# SEED-3: (name, kind, areas, min, max)
EXERCISES = [
    ("Neck side stretch", "stretch", ["neck"], 1, 6),
    ("Chin tucks", "mobility", ["neck"], 1, 5),
    ("Cross-body shoulder stretch", "stretch", ["shoulders"], 1, 7),
    ("Wall slides", "mobility", ["shoulders", "upper_back"], 1, 5),
    ("Thread the needle", "mobility", ["upper_back"], 1, 6),
    ("Cat-cow", "mobility", ["upper_back", "lower_back", "core"], 1, 7),
    ("Child's pose", "stretch", ["lower_back", "hips"], 1, 8),
    ("Knee-to-chest stretch", "stretch", ["lower_back", "glutes"], 1, 7),
    ("Doorway chest stretch", "stretch", ["chest", "shoulders"], 1, 6),
    ("Overhead triceps stretch", "stretch", ["arms"], 1, 6),
    ("Wall biceps stretch", "stretch", ["arms", "elbows"], 1, 6),
    ("Wrist flexor stretch", "stretch", ["wrists_hands", "elbows"], 1, 6),
    ("Wrist circles", "mobility", ["wrists_hands"], 1, 4),
    ("Dead bug", "mobility", ["core"], 1, 4),
    ("Kneeling hip flexor stretch", "stretch", ["hips", "quads"], 1, 7),
    ("90/90 hip switches", "mobility", ["hips", "glutes"], 1, 5),
    ("Figure-four stretch", "stretch", ["glutes", "hips"], 1, 7),
    ("Standing quad stretch", "stretch", ["quads", "knees"], 1, 7),
    ("Seated hamstring stretch", "stretch", ["hamstrings"], 1, 7),
    ("Leg swings", "mobility", ["hamstrings", "hips"], 1, 4),
    ("Heel slides", "mobility", ["knees"], 1, 5),
    ("Wall calf stretch", "stretch", ["calves"], 1, 7),
    ("Ankle circles", "mobility", ["ankles_feet"], 1, 4),
    ("Plantar fascia stretch", "stretch", ["ankles_feet", "calves"], 1, 6),
]


class Command(BaseCommand):
    help = "Create the launch sports, default commission rows and placeholder exercises (safe to run again)."

    @transaction.atomic
    def handle(self, *args, **options):
        # SEED-1: sports, created by name if missing.
        for name in SPORTS:
            Sport.objects.get_or_create(name=name)

        # SEED-2 / COM-4: a default row (no club, no coach) only if none exists, never edited afterwards.
        today = timezone.now().date()
        for applies_to in CommissionRate.AppliesTo.values:
            if not CommissionRate.objects.filter(applies_to=applies_to, club=None, coach=None).exists():
                CommissionRate.objects.create(applies_to=applies_to, percent="10.00", min_count=0, effective_from=today)

        # SEED-3: exercises, created by name if missing; existing ones (areas included) are left alone.
        for name, kind, areas, low, high in EXERCISES:
            exercise, created = Exercise.objects.get_or_create(
                name=name,
                defaults={"kind": kind, "min_soreness": low, "max_soreness": high, "description": PLACEHOLDER},
            )
            if created:
                ExerciseBodyArea.objects.bulk_create(ExerciseBodyArea(exercise=exercise, body_area=a) for a in areas)
