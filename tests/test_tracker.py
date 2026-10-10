import json
from datetime import date

import pytest

from careerforge.models import Profile, ProfileError
from careerforge.tracker import Tracker, dump_file, load_file

D = date(2026, 10, 1)


def tracker_with_one(status="applied"):
    t, app = Tracker().add(
        "Northwind", "Backend Engineer", url="northwind.com/jobs/1", status=status, on=D, ats_score=82
    )
    return t, app


class TestOperations:
    def test_add_creates_event_and_applied_date_only_when_applied(self):
        t, a = tracker_with_one("applied")
        assert (
            a.applied_on == "2026-10-01" and a.events[0].status == "applied" and a.url == "https://northwind.com/jobs/1"
        )
        _, saved = Tracker().add("X", "Y", on=D)
        assert saved.status == "saved" and saved.applied_on == ""

    def test_move_records_history_sets_applied_date_once(self):
        t, a = Tracker().add("X", "Y", on=D)
        t = t.move(a.id, "applied", on=date(2026, 10, 3))
        t = t.move(a.id, "interview", on=date(2026, 10, 9), note="phone screen")
        got = t.get(a.id)
        assert got.status == "interview" and got.applied_on == "2026-10-03"
        assert [(e.status, e.on) for e in got.events] == [
            ("saved", "2026-10-01"),
            ("applied", "2026-10-03"),
            ("interview", "2026-10-09"),
        ]
        assert got.events[-1].note == "phone screen"

    def test_operations_do_not_mutate_the_original(self):
        t, a = tracker_with_one()
        t2 = t.move(a.id, "rejected", on=D)
        assert t.get(a.id).status == "applied" and t2.get(a.id).status == "rejected"

    def test_update_validates_and_protects_managed_fields(self):
        t, a = tracker_with_one()
        assert t.update(a.id, notes="spoke to Ms. Rao").get(a.id).notes == "spoke to Ms. Rao"
        for bad in ({"status": "offer"}, {"id": "abcabcabcabc"}, {"events": []}):
            with pytest.raises(ValueError):
                t.update(a.id, **bad)
        with pytest.raises(ValueError):
            t.update(a.id, ats_score=150)
        with pytest.raises(ValueError):
            t.update(a.id, url="javascript:alert(1)")

    def test_remove_and_unknown_ids(self):
        t, a = tracker_with_one()
        assert t.remove(a.id).applications == []
        for op in (lambda: t.get("nope"), lambda: t.move("nope", "offer"), lambda: t.remove("nope")):
            with pytest.raises(KeyError):
                op()

    def test_by_status_groups_every_column(self):
        t, a = tracker_with_one()
        cols = t.by_status()
        assert list(cols) == ["saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"]
        assert [x.id for x in cols["applied"]] == [a.id] and cols["offer"] == []

    def test_hostile_text_is_stored_inertly_and_bounded(self):
        t, a = Tracker().add("<script>alert(1)</script>", "R&D ‮", on=D, notes="x" * 900)
        assert a.company == "<script>alert(1)</script>" and "‮" not in a.role
        with pytest.raises(ValueError):
            Tracker().add("x" * 101, "y")


class TestFollowUps:
    def due(self, today, **kw):
        t, a = tracker_with_one()
        for k in kw.get("sent", []):
            t = t.mark_followup_sent(a.id, k)
        return [(f.kind, f.due_on, f.overdue_days) for f in t.due(today)]

    def test_nothing_due_before_day_7(self):
        assert self.due(date(2026, 10, 7)) == []

    def test_day_7_then_14_then_close_out(self):
        assert self.due(date(2026, 10, 8)) == [("follow_up_1", "2026-10-08", 0)]
        assert [k for k, *_ in self.due(date(2026, 10, 15))] == ["follow_up_1", "follow_up_2"]
        # most overdue first: day-7 (14 days late), day-14 (7 days late), then the day-21 close-out (due today)
        assert [k for k, *_ in self.due(date(2026, 10, 22))] == ["follow_up_1", "follow_up_2", "close_out"]

    def test_sent_follow_ups_are_not_due_again(self):
        assert self.due(date(2026, 10, 15), sent=["follow_up_1"]) == [("follow_up_2", "2026-10-15", 0)]
        assert [k for k, *_ in self.due(date(2026, 10, 15), sent=["follow_up_1", "follow_up_1", "follow_up_2"])] == []

    def test_only_applied_applications_have_follow_ups(self):
        for status in ("saved", "screening", "interview", "offer", "rejected", "withdrawn"):
            t, a = tracker_with_one()
            assert t.move(a.id, status, on=D).due(date(2027, 1, 1)) == []

    def test_most_overdue_first(self):
        t, a = Tracker().add("Old Co", "Dev", status="applied", on=date(2026, 9, 1))
        t, _ = t.add("New Co", "Dev", status="applied", on=date(2026, 10, 1))
        assert t.due(date(2026, 10, 10))[0].company == "Old Co"


class TestFile:
    P = Profile(name="Priya Nair")

    def test_round_trip_keeps_profile_and_every_application(self):
        t, a = tracker_with_one()
        t = t.move(a.id, "interview", on=date(2026, 10, 9), note="round 1")
        p2, t2 = load_file(dump_file(self.P, t))
        assert p2 == self.P and t2 == t

    def test_an_older_reader_still_loads_the_profile_and_ignores_the_tracker(self):
        t, _ = tracker_with_one()
        assert Profile.from_json(dump_file(self.P, t)) == self.P

    def test_file_without_a_tracker_loads_with_an_empty_one(self):
        assert load_file(self.P.to_json())[1].applications == []
        assert "applications" not in json.loads(dump_file(self.P, Tracker()))

    @pytest.mark.parametrize("apps,msg", [
        ({"not": "a list"}, "must be a list"),
        ([{"company": "X", "status": "ghosted"}], "status"),
        ([{"company": "X", "applied_on": "31/10/2026"}], "applied_on"),
        ([{"company": "X", "id": "../../etc"}], "id"),
        ([{"company": "X", "ats_score": 500}], "ats_score"),
    ])  # fmt: skip
    def test_bad_tracker_data_gives_a_clear_error(self, apps, msg):
        env = json.loads(self.P.to_json())
        env["applications"] = apps
        with pytest.raises(ProfileError, match=msg):
            load_file(json.dumps(env))

    def test_corrupt_files_still_raise_profile_errors(self):
        with pytest.raises(ProfileError):
            load_file("not json")
