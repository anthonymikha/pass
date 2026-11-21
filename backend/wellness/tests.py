import datetime as dt
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts import services as accounts
from accounts.models import Connection, Device, User
from billing.models import CommissionRate
from bookings.models import Session, SessionParticipant
from teams.models import Group, GroupMember
from venues.models import Sport
from wellness.management.commands import seed
from wellness.models import (
    BodyArea, Exercise, ExerciseAssignment, ExerciseBodyArea, SleepLog, SorenessLog, UserAchievement,
)


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


# --- API workflow tests ---

PASSWORD = "court-side-42"
UTC = dt.timezone.utc


def at(*args):
    return dt.datetime(*args, tzinfo=UTC)


class WellnessBase(APITestCase):
    now = at(2027, 1, 12, 12, 0)

    def setUp(self):
        accounts.outbox.clear()
        self.enterContext(mock.patch("django.utils.timezone.now", side_effect=lambda: self.now))
        self.sport = Sport.objects.create(name="Padel")

    def user(self, name, **fields):
        user = User.objects.create_user(f"{name}@example.com", PASSWORD, full_name=name.title(), **fields)
        Device.objects.create(user=user, token=f"tok-{name}", platform="web")  # so pushes reach them
        return user

    def call(self, method, path, user, data=None, expect=None, push=False):
        self.client.force_authenticate(user)
        if push:
            with self.captureOnCommitCallbacks(execute=True):
                r = getattr(self.client, method)(f"/api/{path}", data, format="json")
        else:
            r = getattr(self.client, method)(f"/api/{path}", data, format="json")
        if expect:
            self.assertEqual(r.status_code, expect, (method, path, data, r.data if r.content else None))
        return r

    def session(self, booker, starts_at, ends_at, status="confirmed"):
        return Session.objects.create(
            sport=self.sport, booked_by=booker, kind="play", status=status,
            starts_at=starts_at, ends_at=ends_at, currency="USD", price=0)

    def join(self, session, user, checked_in=True):
        return SessionParticipant.objects.create(
            session=session, user=user, status="accepted", checked_in_at=self.now if checked_in else None)

    def exercise(self, name, areas, low=1, high=10):
        ex = Exercise.objects.create(name=name, kind="stretch", min_soreness=low, max_soreness=high)
        for area in areas:
            ExerciseBodyArea.objects.create(exercise=ex, body_area=area)
        return ex

    def pushed_to(self, user, kind):
        return [p for p in accounts.outbox if p["user_id"] == user.id and p["data"]["type"] == kind]


def sore(rows):
    return sorted((r.body_area, r.level) for r in rows)


class RpeTests(WellnessBase):
    def test_rpe_journey(self):
        """WEL-1, WEL-2, WEL-3, WEL-4, GEN-3, GEN-4, GEN-8: log, replace, refuse, close after 7 days."""
        pat = self.user("pat", timezone="Asia/Tokyo")
        sam = self.user("sam")
        # 2027-01-11 15:30Z to 17:15Z is 2027-01-12 00:30 in Tokyo: the soreness is dated by the user's timezone
        sess = self.session(sam, at(2027, 1, 11, 15, 30), at(2027, 1, 11, 17, 15))
        self.join(sess, pat)
        url = f"sessions/{sess.id}/rpe/"
        row = lambda: SessionParticipant.objects.get(session=sess, user=pat)  # noqa: E731

        r = self.call("put", url, pat, {"rpe": 7, "sore_areas": [
            {"body_area": "quads", "level": 6}, {"body_area": "calves", "level": 0}]}, 200)
        self.assertEqual((r.data["rpe"], r.data["rpe_minutes"]), (7, 105))  # default = session length, rounded down
        self.assertEqual(r.data["sore_areas"], [{"body_area": "quads", "level": 6}, {"body_area": "calves", "level": 0}])
        self.assertEqual(row().rpe_logged_at, self.now)
        rows = SorenessLog.objects.filter(user=pat)
        self.assertEqual(sore(rows), [("calves", 0), ("quads", 6)])
        self.assertEqual({(x.period, x.session_id, x.logged_on) for x in rows},
                         {("post_session", sess.id, dt.date(2027, 1, 12))})

        # an edit replaces both the RPE and the soreness rows
        self.now = at(2027, 1, 12, 13, 0)
        self.call("put", url, pat, {"rpe": 5, "rpe_minutes": 90, "sore_areas": [{"body_area": "knees", "level": 3}]}, 200)
        self.assertEqual((row().rpe, row().rpe_minutes, row().rpe_logged_at), (5, 90, self.now))
        self.assertEqual(sore(SorenessLog.objects.filter(user=pat)), [("knees", 3)])
        self.call("put", url, pat, {"rpe": 5}, 200)  # no sore_areas: none are sore
        self.assertEqual(row().rpe_minutes, 105)
        self.assertFalse(SorenessLog.objects.filter(user=pat).exists())

        # bad values, one error per field, nothing written
        self.call("put", url, pat, {"rpe": 3, "sore_areas": [{"body_area": "knees", "level": 3}]}, 200)
        bad = [
            ({}, "rpe"), ({"rpe": 0}, "rpe"), ({"rpe": 11}, "rpe"), ({"rpe": "x"}, "rpe"), ({"rpe": 5.5}, "rpe"),
            ({"rpe": 5, "rpe_minutes": 0}, "rpe_minutes"), ({"rpe": 5, "rpe_minutes": 601}, "rpe_minutes"),
            ({"rpe": 5, "sore_areas": [{"body_area": "tail", "level": 1}]}, "sore_areas"),
            ({"rpe": 5, "sore_areas": [{"body_area": "knees", "level": 11}]}, "sore_areas"),
            ({"rpe": 5, "sore_areas": [{"body_area": "knees", "level": -1}]}, "sore_areas"),
            ({"rpe": 5, "sore_areas": [{"body_area": "knees", "level": 1}, {"body_area": "knees", "level": 2}]}, "sore_areas"),
        ]
        for body, field in bad:
            r = self.call("put", url, pat, body)
            self.assertEqual(r.status_code, 400, body)
            self.assertIn(field, r.data, body)
        self.assertEqual((row().rpe, sore(SorenessLog.objects.filter(user=pat))), (3, [("knees", 3)]))

        # another user's row, or no row at all: 404 before the input is even read (GEN-3, GEN-4)
        self.call("put", url, self.user("lee"), {"rpe": 5}, 404)
        self.call("put", url, sam, {"rpe": 99}, 404)  # sam booked it but has no participant row
        self.call("put", "sessions/9999/rpe/", pat, {"rpe": 5}, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.put(f"/api/{url}", {"rpe": 5}, format="json").status_code, 401)

        # the window: ends_at + 7 days is still open, one second later is closed
        self.now = at(2027, 1, 18, 17, 15)
        self.call("put", url, pat, {"rpe": 6}, 200)
        self.now = at(2027, 1, 18, 17, 15, 1)
        r = self.call("put", url, pat, {"rpe": 9}, 400)
        self.assertEqual(r.data["code"], "rpe_closed")
        self.assertEqual(row().rpe, 6)

    def test_rpe_needs_a_check_in_and_keeps_sessions_apart(self):
        """WEL-1, WEL-3, WEL-4: not checked in is refused; two sessions on one day keep separate post-session rows."""
        pat = self.user("pat")
        sam = self.user("sam")
        a = self.session(sam, at(2027, 1, 12, 8, 0), at(2027, 1, 12, 9, 0))
        b = self.session(sam, at(2027, 1, 12, 10, 0), at(2027, 1, 12, 11, 0))
        absent = self.session(sam, at(2027, 1, 12, 6, 0), at(2027, 1, 12, 7, 0))
        cancelled = self.session(sam, at(2027, 1, 12, 4, 0), at(2027, 1, 12, 5, 0), status="cancelled")
        self.join(a, pat)
        self.join(b, pat)
        self.join(absent, pat, checked_in=False)
        self.join(cancelled, pat)

        for s, code in ((absent, "not_checked_in"), (cancelled, "invalid_status")):
            r = self.call("put", f"sessions/{s.id}/rpe/", pat, {"rpe": 5}, 400)
            self.assertEqual(r.data["code"], code)
        self.assertIsNone(SessionParticipant.objects.get(session=absent, user=pat).rpe)

        self.call("put", f"sessions/{a.id}/rpe/", pat, {"rpe": 5, "sore_areas": [{"body_area": "hips", "level": 2}]}, 200)
        self.call("put", f"sessions/{b.id}/rpe/", pat, {"rpe": 8, "sore_areas": [{"body_area": "hips", "level": 7}]}, 200)
        self.call("put", f"sessions/{a.id}/rpe/", pat, {"rpe": 4, "sore_areas": [{"body_area": "hips", "level": 1}]}, 200)
        by_session = {x.session_id: x.level for x in SorenessLog.objects.filter(user=pat)}
        self.assertEqual(by_session, {a.id: 1, b.id: 7})  # editing one session leaves the other alone
        self.assertEqual(SorenessLog.objects.filter(user=pat).count(), 2)
        # post-session rows are listed with their session
        rows = self.call("get", "soreness/", pat, expect=200).data["results"]
        self.assertEqual({(x["period"], x["session"]) for x in rows}, {("post_session", a.id), ("post_session", b.id)})


class SorenessTests(WellnessBase):
    def test_soreness_journey(self):
        """WEL-10, WEL-11, WEL-12, WEL-30, WEL-31, WEL-32, GEN-8, ACC-4: check in, replace, delete, suggestions."""
        # 2027-01-12 20:00Z is already 2027-01-13 in Tokyo
        self.now = at(2027, 1, 12, 20, 0)
        pat = self.user("pat", timezone="Asia/Tokyo")
        self.exercise("Quad stretch", ["quads"], 1, 5)
        self.exercise("Quad foam roll", ["quads"], 4, 10)
        self.exercise("Aardvark walk", ["quads", "calves"], 3, 6)
        self.exercise("Calf stretch", ["calves"], 1, 10)

        r = self.call("post", "soreness/", pat, {"period": "morning", "areas": [
            {"body_area": "quads", "level": 5}, {"body_area": "calves", "level": 0}, {"body_area": "knees", "level": 4}]}, 200)
        self.assertEqual(str(r.data["logged_on"]), "2027-01-13")  # today in the user's timezone
        names = [(s["body_area"], s["level"], [e["name"] for e in s["exercises"]]) for s in r.data["suggestions"]]
        self.assertEqual(names, [
            ("quads", 5, ["Aardvark walk", "Quad foam roll", "Quad stretch"]),  # level 5 is in range, sorted by name
            ("knees", 4, []),  # no exercise for the area: an empty list, no error
        ])  # calves at level 0 gets no suggestions at all
        self.assertEqual(sore(SorenessLog.objects.filter(user=pat)), [("calves", 0), ("knees", 4), ("quads", 5)])
        self.assertFalse(ExerciseAssignment.objects.exists())  # suggestions are computed, not stored (WEL-32)

        # range edges: level 6 loses "Quad stretch" (max 5), level 3 loses "Quad foam roll" (min 4)
        def names_for(level):
            r = self.call("post", "soreness/", pat, {"period": "evening", "areas": [{"body_area": "quads", "level": level}]}, 200)
            return [e["name"] for e in r.data["suggestions"][0]["exercises"]]
        self.assertEqual(names_for(6), ["Aardvark walk", "Quad foam roll"])
        self.assertEqual(names_for(3), ["Aardvark walk", "Quad stretch"])
        self.assertEqual(names_for(8), ["Quad foam roll"])  # the evening row now says quads 8

        # sending the morning check-in again replaces only the morning rows
        self.call("post", "soreness/", pat, {"period": "morning", "areas": [{"body_area": "quads", "level": 2}]}, 200)
        morning = SorenessLog.objects.filter(user=pat, period="morning")
        self.assertEqual(sore(morning), [("quads", 2)])
        self.assertEqual(sore(SorenessLog.objects.filter(user=pat, period="evening")), [("quads", 8)])

        # today's suggestions: the highest level per area across periods (WEL-31)
        self.call("post", "soreness/", pat, {"period": "evening", "areas": [
            {"body_area": "quads", "level": 8}, {"body_area": "hips", "level": 3}, {"body_area": "neck", "level": 0}]}, 200)
        SorenessLog.objects.create(user=pat, logged_on=dt.date(2027, 1, 12), period="evening", body_area="calves", level=9)
        r = self.call("get", "soreness/suggestions/", pat, expect=200)
        self.assertEqual([(s["body_area"], s["level"], [e["name"] for e in s["exercises"]]) for s in r.data], [
            ("hips", 3, []),
            ("quads", 8, ["Quad foam roll"]),  # morning said 2, evening said 8: 8 wins; yesterday's calves are not today's
        ])
        self.assertFalse(ExerciseAssignment.objects.exists())

        # an empty list deletes the check-in
        r = self.call("post", "soreness/", pat, {"period": "evening", "areas": []}, 200)
        self.assertEqual(r.data["suggestions"], [])
        self.assertFalse(SorenessLog.objects.filter(user=pat, period="evening", logged_on=dt.date(2027, 1, 13)).exists())
        self.assertTrue(SorenessLog.objects.filter(user=pat, period="morning").exists())

        # logged_on: today and 7 days back are fine; the future and 8 days back are not
        ok = lambda day: self.call("post", "soreness/", pat, {"period": "evening", "logged_on": day, "areas": []})  # noqa: E731
        self.assertEqual(ok("2027-01-13").status_code, 200)
        self.assertEqual(ok("2027-01-06").status_code, 200)
        for day in ("2027-01-05", "2027-01-14", "not-a-date"):
            self.assertIn("logged_on", ok(day).data, day)

        # a past day's check-in is kept apart from today's
        self.call("post", "soreness/", pat, {"period": "morning", "logged_on": "2027-01-10", "areas": [{"body_area": "neck", "level": 1}]}, 200)
        self.assertEqual(SorenessLog.objects.filter(user=pat, logged_on=dt.date(2027, 1, 10)).count(), 1)
        self.assertEqual(sore(SorenessLog.objects.filter(user=pat, logged_on=dt.date(2027, 1, 13))), [("quads", 2)])

        # bad input, one error per field
        bad = [
            ({"areas": []}, "period"), ({"period": "post_session", "areas": []}, "period"), ({"period": "noon", "areas": []}, "period"),
            ({"period": "morning"}, "areas"),
            ({"period": "morning", "areas": [{"body_area": "quads", "level": 11}]}, "areas"),
            ({"period": "morning", "areas": [{"body_area": "tail", "level": 1}]}, "areas"),
            ({"period": "morning", "areas": [{"body_area": "quads", "level": 1}, {"body_area": "quads", "level": 2}]}, "areas"),
        ]
        for body, field in bad:
            self.assertIn(field, self.call("post", "soreness/", pat, body, 400).data, body)

        # a user reads their own logs only (ACC-4)
        mine = self.call("get", "soreness/", pat, expect=200).data["results"]
        self.assertEqual(len(mine), SorenessLog.objects.filter(user=pat).count())
        self.assertEqual(self.call("get", "soreness/", self.user("sam"), expect=200).data["results"], [])


class SleepTests(WellnessBase):
    def test_manual_sleep_journey(self):
        """WEL-20, ACC-4, GEN-3, GEN-7: create, change, delete a manual entry; the checks on the times."""
        pat, sam = self.user("pat"), self.user("sam")
        body = {"sleep_start": "2027-01-11T22:00:00Z", "sleep_end": "2027-01-12T06:00:00+00:00"}
        r = self.call("post", "sleep/", pat, body, 201)
        self.assertEqual((r.data["source"], r.data["external_id"]), ("manual", ""))
        row = SleepLog.objects.get(pk=r.data["id"])
        self.assertEqual((row.user, row.sleep_end), (pat, at(2027, 1, 12, 6, 0)))

        bad = [
            {}, {"sleep_start": body["sleep_start"]},
            {"sleep_start": "2027-01-12T06:00:00Z", "sleep_end": "2027-01-12T06:00:00Z"},  # not after the start
            {"sleep_start": "2027-01-12T07:00:00Z", "sleep_end": "2027-01-12T06:00:00Z"},
            {"sleep_start": "2027-01-10T10:00:00Z", "sleep_end": "2027-01-11T10:00:01Z"},  # 24 hours and a second
            {"sleep_start": "2027-01-12T10:00:00Z", "sleep_end": "2027-01-12T12:00:01Z"},  # ends after now
            {"sleep_start": "2027-01-11T22:00:00", "sleep_end": "2027-01-12T06:00:00"},  # no offset (GEN-7)
        ]
        for b in bad:
            self.assertEqual(self.call("post", "sleep/", pat, b).status_code, 400, b)
        self.call("post", "sleep/", pat, {"sleep_start": "2027-01-10T10:00:00Z", "sleep_end": "2027-01-11T10:00:00Z"}, 201)  # exactly 24 h
        self.call("post", "sleep/", pat, {"sleep_start": "2027-01-12T10:00:00Z", "sleep_end": "2027-01-12T12:00:00Z"}, 201)  # ends now

        # change: only the sent field moves, the result is checked as a whole
        r = self.call("patch", f"sleep/{row.id}/", pat, {"sleep_end": "2027-01-12T07:00:00Z"}, 200)
        self.assertEqual(r.data["sleep_end"], "2027-01-12T07:00:00Z")
        self.call("patch", f"sleep/{row.id}/", pat, {"sleep_start": "2027-01-12T08:00:00Z"}, 400)
        row.refresh_from_db()
        self.assertEqual((row.sleep_start, row.sleep_end), (at(2027, 1, 11, 22, 0), at(2027, 1, 12, 7, 0)))

        # imported rows are not editable by hand
        imported = SleepLog.objects.create(user=pat, source="apple_health", external_id="x", sleep_start=at(2027, 1, 9, 22), sleep_end=at(2027, 1, 10, 6))
        self.call("patch", f"sleep/{imported.id}/", pat, {"sleep_end": "2027-01-10T07:00:00Z"}, 403)

        # someone else's row does not exist for you
        self.call("patch", f"sleep/{row.id}/", sam, {"sleep_end": "2027-01-12T05:00:00Z"}, 404)
        self.call("delete", f"sleep/{row.id}/", sam, expect=404)
        self.assertEqual(self.call("get", "sleep/", sam, expect=200).data["results"], [])
        listed = self.call("get", "sleep/", pat, expect=200).data["results"]
        self.assertEqual([x["id"] for x in listed][0], SleepLog.objects.filter(user=pat).order_by("-sleep_start")[0].id)
        self.assertEqual(len(listed), 4)

        self.call("delete", f"sleep/{row.id}/", pat, expect=204)
        self.assertFalse(SleepLog.objects.filter(pk=row.id).exists())
        self.call("delete", f"sleep/{row.id}/", pat, expect=404)

    def test_phone_import_journey(self):
        """WEL-21, WEL-22, WEL-23, ACC-4: bulk import, upsert, all-or-nothing, 500 limit, delete then re-import."""
        pat, sam = self.user("pat"), self.user("sam")

        def rec(i, source="apple_health", start="2027-01-11T22:00:00Z", end="2027-01-12T06:00:00Z"):
            return {"source": source, "external_id": f"night-{i}", "sleep_start": start, "sleep_end": end}

        r = self.call("post", "sleep/import/", pat, {"records": [rec(1), rec(2), rec(3, "health_connect")]}, 200)
        self.assertEqual(r.data, {"created": 3, "updated": 0})
        self.assertEqual(SleepLog.objects.filter(user=pat).count(), 3)

        # the same night again, with new times: updated, not duplicated (WEL-21)
        r = self.call("post", "sleep/import/", pat, {"records": [
            rec(1, end="2027-01-12T07:00:00Z"), rec(2), rec(4)]}, 200)
        self.assertEqual(r.data, {"created": 1, "updated": 2})
        self.assertEqual(SleepLog.objects.filter(user=pat).count(), 4)
        self.assertEqual(SleepLog.objects.get(user=pat, external_id="night-1").sleep_end, at(2027, 1, 12, 7, 0))
        # the same external id under another source, or for another user, is another record
        r = self.call("post", "sleep/import/", pat, {"records": [rec(1, "health_connect")]}, 200)
        self.assertEqual(r.data, {"created": 1, "updated": 0})
        self.call("post", "sleep/import/", sam, {"records": [rec(1)]}, 200)
        self.assertEqual(SleepLog.objects.filter(external_id="night-1").count(), 3)
        self.assertEqual(SleepLog.objects.filter(user=pat).count(), 5)
        self.assertEqual(SleepLog.objects.get(user=pat, source="apple_health", external_id="night-1").sleep_end, at(2027, 1, 12, 7, 0))

        # one invalid record: nothing is written, the errors are by list index
        before = list(SleepLog.objects.order_by("id").values())
        r = self.call("post", "sleep/import/", pat, {"records": [
            rec(1, end="2027-01-12T09:00:00Z"), rec(5), rec(6, end="2027-01-11T21:00:00Z"),
            {**rec(7), "source": "manual"}, {**rec(8), "external_id": ""}, {**rec(9), "external_id": "x" * 129}]})
        self.assertEqual(r.status_code, 400)
        errors = r.data["records"]  # keyed by the index of the bad record
        self.assertEqual(sorted(errors), [2, 3, 4, 5])
        self.assertIn("sleep_end", errors[2])
        self.assertIn("source", errors[3])
        self.assertIn("external_id", errors[4])
        self.assertIn("external_id", errors[5])
        self.assertEqual(list(SleepLog.objects.order_by("id").values()), before)

        # 500 are accepted, 501 are refused and nothing is written
        many = lambda n: {"records": [rec(i, "health_connect") for i in range(100, 100 + n)]}  # noqa: E731
        self.assertEqual(self.call("post", "sleep/import/", pat, many(501)).status_code, 400)
        self.assertEqual(SleepLog.objects.filter(user=pat).count(), 5)
        r = self.call("post", "sleep/import/", pat, many(500), 200)
        self.assertEqual(r.data, {"created": 500, "updated": 0})
        self.assertEqual(self.call("post", "sleep/import/", pat, {"records": []}, 200).data, {"created": 0, "updated": 0})
        self.assertEqual(self.call("post", "sleep/import/", pat, {}).status_code, 400)

        # deleting an imported row and importing it again creates it again (WEL-22)
        gone = SleepLog.objects.get(user=pat, source="apple_health", external_id="night-2")
        self.call("delete", f"sleep/{gone.id}/", pat, expect=204)
        r = self.call("post", "sleep/import/", pat, {"records": [rec(2)]}, 200)
        self.assertEqual(r.data, {"created": 1, "updated": 0})

        # WEL-23: profile data from the phone goes to PATCH /api/me/
        r = self.call("patch", "me/", pat, {"height_cm": "180.5", "weight_kg": "75.20", "date_of_birth": "1990-05-04", "sex": "female"}, 200)
        self.assertEqual((r.data["height_cm"], r.data["sex"]), ("180.5", "female"))


class ExerciseTests(WellnessBase):
    def test_pick_complete_delete_journey(self):
        """WEL-32, WEL-33, WEL-42, WEL-43, WEL-44, GEN-5, GEN-18, ACC-4: pick, repeat, complete, list, delete."""
        pat, sam = self.user("pat", timezone="Asia/Tokyo"), self.user("sam")
        stretch = self.exercise("Quad stretch", ["quads"])
        roll = self.exercise("Calf roll", ["calves"])

        self.assertEqual([e["name"] for e in self.call("get", "exercises/", pat, expect=200).data["results"]],
                         ["Calf roll", "Quad stretch"])

        # 12:00Z is 21:00 on the 12th in Tokyo, so "today" for due_on is 2027-01-12
        r = self.call("post", "exercise-assignments/", pat, {
            "exercise": stretch.id, "sets": 3, "reps": 10, "hold_seconds": 30, "due_on": "2027-01-12"}, 201)
        self.assertIsNone(r.data["assigned_by"])
        self.assertIsNone(r.data["group"])
        self.assertEqual((r.data["sets"], r.data["reps"], r.data["hold_seconds"], r.data["due_on"]), (3, 10, 30, "2027-01-12"))
        self.assertEqual(r.data["exercise"]["name"], "Quad stretch")
        first = r.data["id"]
        # picking it again returns the open one (even with other numbers): 200, same row, no new row
        r = self.call("post", "exercise-assignments/", pat, {"exercise": stretch.id, "sets": 9}, 200)
        self.assertEqual((r.data["id"], r.data["sets"]), (first, 3))
        self.assertEqual(ExerciseAssignment.objects.count(), 1)
        # another exercise, and another user's pick, are separate
        self.call("post", "exercise-assignments/", pat, {"exercise": roll.id}, 201)
        self.call("post", "exercise-assignments/", sam, {"exercise": stretch.id}, 201)

        bad = [
            {}, {"exercise": 9999}, {"exercise": stretch.id, "sets": 0}, {"exercise": stretch.id, "reps": 1000},
            {"exercise": stretch.id, "hold_seconds": 0}, {"exercise": stretch.id, "due_on": "2027-01-11"},
        ]
        for b in bad:
            r = self.call("post", "exercise-assignments/", pat, b)
            self.assertEqual(r.status_code, 400, b)
        self.assertEqual(self.call("post", "exercise-assignments/", pat, {"exercise": 9999}).data["exercise"], ["Not found."])
        self.call("post", "exercise-assignments/", pat, {"exercise": stretch.id, "due_on": "2027-01-13"}, 200)  # a repeat, not a new row

        # complete: 200, a repeat changes nothing; someone else's is a 404
        self.call("post", f"exercise-assignments/{first}/complete/", sam, expect=404)
        r = self.call("post", f"exercise-assignments/{first}/complete/", pat, expect=200)
        done_at = r.data["completed_at"]
        self.assertEqual(done_at, "2027-01-12T12:00:00Z")
        self.now = at(2027, 1, 12, 15, 0)
        r = self.call("post", f"exercise-assignments/{first}/complete/", pat, expect=200)
        self.assertEqual(r.data["completed_at"], done_at)
        self.call("post", "exercise-assignments/9999/complete/", pat, expect=404)

        # list, with the open / done filter, newest first; only the caller's own
        listed = lambda user, q="": self.call("get", f"exercise-assignments/{q}", user, expect=200).data["results"]  # noqa: E731
        self.assertEqual(len(listed(pat)), 2)
        self.assertEqual([x["exercise"]["name"] for x in listed(pat, "?status=open")], ["Calf roll"])
        self.assertEqual([x["id"] for x in listed(pat, "?status=done")], [first])
        self.assertEqual(self.call("get", "exercise-assignments/?status=late", pat).status_code, 400)
        self.assertEqual(len(listed(sam)), 1)

        # once done, the same exercise can be picked again as a new row
        r = self.call("post", "exercise-assignments/", pat, {"exercise": stretch.id}, 201)
        self.assertNotEqual(r.data["id"], first)

        # delete: the user's own open pick goes; a completed one stays; someone else's is a 404
        self.call("delete", f"exercise-assignments/{first}/", pat, expect=403)
        self.call("delete", f"exercise-assignments/{r.data['id']}/", sam, expect=404)
        self.call("delete", f"exercise-assignments/{r.data['id']}/", pat, expect=204)
        self.call("delete", f"exercise-assignments/{r.data['id']}/", pat, expect=404)
        self.assertTrue(ExerciseAssignment.objects.filter(pk=first).exists())

    def test_coach_sends_to_a_player_and_a_team(self):
        """WEL-40, WEL-41, WEL-43, WEL-44, NOTE-20, ACC-1, ACC-12, GEN-3, GEN-8: coach assignments."""
        # the coach is in Auckland: 12:00Z on the 12th is already 01:00 on the 13th there
        coach = self.user("coach", is_coach=True, timezone="Pacific/Auckland")
        rival = self.user("rival", is_coach=True)
        linked, m1, m2, invited, plain, stranger = (self.user(n) for n in ("linked", "m1", "m2", "invited", "plain", "stranger"))
        kid = User.objects.create_user(email=None, full_name="Kid", managed_by=coach)
        other_kid = User.objects.create_user(email=None, full_name="Rival kid", managed_by=rival)
        Connection.objects.create(user=coach, other_user=linked, type="coaching", status="accepted")
        team = Group.objects.create(type="team", name="Tigers", created_by=coach, coach=coach)
        for u, st in ((coach, "active"), (m1, "active"), (m2, "active"), (kid, "active"), (invited, "invited")):
            GroupMember.objects.create(group=team, user=u, status=st)
        park = Group.objects.create(type="play_group", name="Park", created_by=coach)
        GroupMember.objects.create(group=park, user=m1, status="active")
        stretch = self.exercise("Quad stretch", ["quads"])

        # to one of the coach's players: a row with no group, a push to that player only
        url = lambda uid: f"players/{uid}/exercise-assignments/"  # noqa: E731
        r = self.call("post", url(linked.id), coach, {"exercise": stretch.id, "sets": 2, "due_on": "2027-01-13"}, 201, push=True)
        self.assertEqual((r.data["assigned_by"], r.data["group"], r.data["user"]), (coach.id, None, linked.id))
        pushes = self.pushed_to(linked, "exercise_assigned")
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0]["data"], {"id": str(r.data["id"]), "type": "exercise_assigned"})
        self.assertEqual(len(accounts.outbox), 1)  # nobody else, not the coach
        single = r.data["id"]

        # due_on is checked in the coach's timezone: the 12th is already past in Auckland
        self.assertIn("due_on", self.call("post", url(linked.id), coach, {"exercise": stretch.id, "due_on": "2027-01-12"}, 400).data)
        self.assertIn("exercise", self.call("post", url(linked.id), coach, {"exercise": 9999}, 400).data)

        # not assignable, not visible
        r = self.call("post", url(kid.id), coach, {"exercise": stretch.id}, 400)  # a shadow player (ACC-12)
        self.assertEqual(r.data["code"], "not_assignable")
        self.call("post", url(stranger.id), coach, {"exercise": stretch.id}, 404)  # not the coach's player
        self.call("post", url(other_kid.id), coach, {"exercise": stretch.id}, 404)  # another coach's shadow player
        self.call("post", url(linked.id), rival, {"exercise": stretch.id}, 404)
        self.call("post", url(linked.id), plain, {"exercise": stretch.id}, 404)  # a non-coach has no players
        self.call("post", url(9999), coach, {"exercise": stretch.id}, 404)
        self.assertEqual(ExerciseAssignment.objects.count(), 1)

        # to a team: one row per active non-shadow member except the coach, each with a push
        accounts.outbox.clear()
        r = self.call("post", f"groups/{team.id}/exercise-assignments/", coach, {"exercise": stretch.id, "hold_seconds": 20}, 201, push=True)
        self.assertEqual(sorted(x["user"] for x in r.data), sorted([m1.id, m2.id]))
        self.assertEqual({(x["assigned_by"], x["group"], x["hold_seconds"]) for x in r.data}, {(coach.id, team.id, 20)})
        for member in (m1, m2):
            row = ExerciseAssignment.objects.get(user=member, group=team)
            self.assertEqual([p["data"]["id"] for p in self.pushed_to(member, "exercise_assigned")], [str(row.id)])
        self.assertEqual(len(accounts.outbox), 2)
        self.assertFalse(ExerciseAssignment.objects.filter(user__in=[coach, kid, invited]).exists())

        # who may send to a team: its coach only
        for who in (rival, plain, m1):
            self.call("post", f"groups/{team.id}/exercise-assignments/", who, {"exercise": stretch.id}, 403)
        self.call("post", f"groups/{park.id}/exercise-assignments/", coach, {"exercise": stretch.id}, 403)  # a play group
        self.call("post", "groups/9999/exercise-assignments/", coach, {"exercise": stretch.id}, 404)
        self.assertIn("exercise", self.call("post", f"groups/{team.id}/exercise-assignments/", coach, {}, 400).data)
        self.assertEqual(ExerciseAssignment.objects.count(), 3)

        # a member who leaves keeps their assignment (edge case)
        self.call("delete", f"groups/{team.id}/members/{m1.id}/", m1, expect=204)
        listed = self.call("get", "exercise-assignments/", m1, expect=200).data["results"]
        self.assertEqual([(x["assigned_by"], x["group"]) for x in listed], [(coach.id, team.id)])  # told apart by assigned_by

        # a player cannot delete what a coach sent; the sender may while it is open; completed ones stay
        row = listed[0]["id"]
        self.call("delete", f"exercise-assignments/{row}/", m1, expect=403)
        self.call("delete", f"exercise-assignments/{row}/", rival, expect=404)
        self.call("delete", f"exercise-assignments/{row}/", coach, expect=204)
        self.assertEqual(self.call("get", "exercise-assignments/", m1, expect=200).data["results"], [])
        self.call("post", f"exercise-assignments/{single}/complete/", linked, expect=200)
        self.call("delete", f"exercise-assignments/{single}/", coach, expect=403)
        self.call("delete", f"exercise-assignments/{single}/", linked, expect=403)
        self.assertTrue(ExerciseAssignment.objects.filter(pk=single).exists())

        # a team with nobody but the coach: nothing to send, nothing refused
        solo = Group.objects.create(type="team", name="Solo", created_by=coach, coach=coach)
        GroupMember.objects.create(group=solo, user=coach, status="active")
        self.assertEqual(self.call("post", f"groups/{solo.id}/exercise-assignments/", coach, {"exercise": stretch.id}, 201).data, [])


class AchievementTests(WellnessBase):
    def test_achievements_journey(self):
        """WEL-42, WEL-50, WEL-51, GEN-5, GEN-8: first_exercise once; exercise_streak_7 needs 7 local dates in a row."""
        pat = self.user("pat", timezone="Asia/Tokyo")
        ex = self.exercise("Quad stretch", ["quads"])
        codes = lambda: sorted(UserAchievement.objects.filter(user=pat).values_list("achievement_code", flat=True))  # noqa: E731

        def finish(day, hour):
            """Complete a new assignment at `hour` Tokyo time on January `day`."""
            row = ExerciseAssignment.objects.create(user=pat, exercise=ex)
            self.now = at(2027, 1, day, hour) - dt.timedelta(hours=9)
            self.call("post", f"exercise-assignments/{row.id}/complete/", pat, expect=200)
            return row

        # alternate 20:00 and 08:00 local so the UTC date and the local date disagree for some of them
        hours = {5: 20, 6: 8, 7: 20, 8: 8}
        for day, hour in hours.items():
            finish(day, hour)
        self.assertEqual(codes(), ["first_exercise"])
        self.assertEqual(UserAchievement.objects.get(user=pat).earned_at, at(2027, 1, 5, 11, 0))
        # a second completion on the same local day, and a repeat of one, add nothing
        again = finish(8, 20)
        self.call("post", f"exercise-assignments/{again.id}/complete/", pat, expect=200)
        # 01-09 is missed; 01-10 .. 01-15 are done
        for day in range(10, 16):
            finish(day, 20 if day % 2 == 0 else 8)
            self.assertEqual(codes(), ["first_exercise"], day)  # 01-09 is inside every window until 01-16
        self.assertEqual(ExerciseAssignment.objects.filter(completed_at__isnull=False).count(), 11)

        finish(16, 8)  # 01-10 .. 01-16: seven local dates in a row, today included
        self.assertEqual(codes(), ["exercise_streak_7", "first_exercise"])
        earned = UserAchievement.objects.get(user=pat, achievement_code="exercise_streak_7").earned_at
        self.assertEqual(earned, at(2027, 1, 16, 8) - dt.timedelta(hours=9))
        finish(17, 20)
        self.assertEqual(codes(), ["exercise_streak_7", "first_exercise"])  # each is earned once
        self.assertEqual(UserAchievement.objects.get(user=pat, achievement_code="exercise_streak_7").earned_at, earned)

        r = self.call("get", "me/achievements/", pat, expect=200)
        self.assertEqual([x["code"] for x in r.data["results"]], ["first_exercise", "exercise_streak_7"])
        self.assertEqual(self.call("get", "me/achievements/", self.user("sam"), expect=200).data["results"], [])  # ACC-4

    def test_six_days_is_not_a_streak(self):
        """WEL-50: six dates in a row, even with several completions a day, is not exercise_streak_7."""
        pat = self.user("pat")
        ex = self.exercise("Quad stretch", ["quads"])
        for day in range(7, 13):  # 01-07 .. 01-12
            for _ in range(2):
                row = ExerciseAssignment.objects.create(user=pat, exercise=ex)
                self.now = at(2027, 1, day, 12)
                self.call("post", f"exercise-assignments/{row.id}/complete/", pat, expect=200)
        self.assertEqual(list(UserAchievement.objects.values_list("achievement_code", flat=True)), ["first_exercise"])


class CoachReadsTests(WellnessBase):
    def test_coach_reads_their_players_logs(self):
        """TEAM-40, ACC-1, ACC-4, GEN-3: a coach reads a player's soreness, sleep and assignments; nobody else's."""
        coach = self.user("coach", is_coach=True)
        rival = self.user("rival", is_coach=True)
        linked, member, ex_member, stranger, plain = (self.user(n) for n in ("linked", "member", "ex", "stranger", "plain"))
        kid = User.objects.create_user(email=None, full_name="Kid", managed_by=coach)
        Connection.objects.create(user=coach, other_user=linked, type="coaching", status="accepted")
        team = Group.objects.create(type="team", name="Tigers", created_by=coach, coach=coach)
        GroupMember.objects.create(group=team, user=member, status="active")
        GroupMember.objects.create(group=team, user=ex_member, status="invited")  # not (yet) a player
        stretch = self.exercise("Quad stretch", ["quads"])

        for who in (linked, member, stranger):
            self.call("post", "soreness/", who, {"period": "morning", "areas": [{"body_area": "quads", "level": 4}]}, 200)
            self.call("post", "sleep/", who, {"sleep_start": "2027-01-11T22:00:00Z", "sleep_end": "2027-01-12T06:00:00Z"}, 201)
            self.call("post", "exercise-assignments/", who, {"exercise": stretch.id}, 201)  # self-picked
        self.call("post", f"players/{linked.id}/exercise-assignments/", coach, {"exercise": stretch.id}, 201)  # coach-sent

        for kind, count in (("soreness", 1), ("sleep", 1), ("exercise-assignments", 2)):
            r = self.call("get", f"players/{linked.id}/{kind}/", coach, expect=200)
            self.assertEqual(len(r.data["results"]), count, kind)
            self.call("get", f"players/{member.id}/{kind}/", coach, expect=200)  # a team member
            self.assertEqual(self.call("get", f"players/{kid.id}/{kind}/", coach, expect=200).data["results"], [])  # shadow player
            for hidden in (stranger, ex_member, plain):  # not the coach's players
                self.call("get", f"players/{hidden.id}/{kind}/", coach, expect=404)
            self.call("get", f"players/{linked.id}/{kind}/", rival, expect=404)  # another coach
            self.call("get", f"players/{linked.id}/{kind}/", plain, expect=404)  # a non-coach
            self.call("get", f"players/{linked.id}/{kind}/", linked, expect=404)  # the player uses their own endpoint
            self.call("get", f"players/9999/{kind}/", coach, expect=404)
        r = self.call("get", f"players/{linked.id}/exercise-assignments/?status=open", coach, expect=200)
        self.assertEqual(sorted(x["assigned_by"] is None for x in r.data["results"]), [False, True])
        self.assertEqual(self.call("get", f"players/{linked.id}/soreness/", coach).data["results"][0]["body_area"], "quads")

        # reading is all a coach does with logs: no writing soreness or sleep for a player
        self.call("post", f"players/{linked.id}/soreness/", coach, {"period": "morning", "areas": []}, 405)
        self.call("post", f"players/{linked.id}/sleep/", coach, {"sleep_start": "2027-01-11T22:00:00Z", "sleep_end": "2027-01-12T06:00:00Z"}, 405)
        self.assertEqual(SorenessLog.objects.filter(user=linked).count(), 1)

        # a player who leaves the coach's team is no longer readable
        GroupMember.objects.filter(user=member).delete()
        self.call("get", f"players/{member.id}/soreness/", coach, expect=404)
