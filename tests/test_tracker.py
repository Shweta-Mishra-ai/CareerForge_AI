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


class TestTrackerV2:
    def test_source_contact_and_next_action_round_trip_through_the_file(self):
        t, a = Tracker().add("Acme", "Dev", on=D, source="LinkedIn", contact="Ms. Rao")
        t = t.update(a.id, next_action="Send thank-you note", next_action_on="2026-10-05")
        _, loaded = load_file(dump_file(Profile(name="A B"), t))
        got = loaded.get(a.id)
        assert (got.source, got.contact, got.next_action, got.next_action_on) == (
            "LinkedIn",
            "Ms. Rao",
            "Send thank-you note",
            "2026-10-05",
        )

    def test_next_action_dates_are_validated(self):
        t, a = Tracker().add("Acme", "Dev", on=D)
        with pytest.raises(ValueError):
            t.update(a.id, next_action_on="next week")

    def test_actions_due_lists_overdue_open_items_most_overdue_first(self):
        t, a = Tracker().add("Acme", "Dev", on=D, status="applied")
        t, b = t.add("Beta", "Dev", on=D, status="applied")
        t, c = t.add("Gamma", "Dev", on=D, status="applied")
        t, d = t.add("Delta", "Dev", on=D, status="offer")
        t = t.update(a.id, next_action="Call", next_action_on="2026-10-08")
        t = t.update(b.id, next_action="Email", next_action_on="2026-10-10")
        t = t.update(c.id, next_action="Later", next_action_on="2026-10-11")
        t = t.update(d.id, next_action="Negotiate", next_action_on="2026-10-01")  # closed: not listed
        due = t.actions_due(date(2026, 10, 10))
        assert [(x.company, x.action, x.overdue_days) for x in due] == [("Acme", "Call", 2), ("Beta", "Email", 0)]

    def test_an_action_without_a_date_or_a_date_without_an_action_is_not_due(self):
        t, a = Tracker().add("Acme", "Dev", on=D)
        assert t.update(a.id, next_action="Call").actions_due(D) == []
        assert t.update(a.id, next_action_on="2026-10-01").actions_due(D) == []

    def test_saved_searches_are_stored_once_and_updated_in_place(self):
        t, one = Tracker().add_search("Backend Engineer", location="Pune")
        t, again = t.add_search("backend engineer", location="PUNE", boards=["https://jobs.lever.co/acme"])
        assert len(t.saved_searches) == 1 and again.id == one.id
        assert t.saved_searches[0].boards == ["https://jobs.lever.co/acme"]
        t, other = t.add_search("Backend Engineer", location="Pune", remote_only=True)
        assert len(t.saved_searches) == 2 and other.id != one.id
        assert [s.id for s in t.remove_search(one.id).saved_searches] == [other.id]

    def test_a_saved_search_needs_a_phrase_and_is_capped(self):
        with pytest.raises(ValueError):
            Tracker().add_search("   ")
        t = Tracker()
        for i in range(20):
            t, _ = t.add_search(f"query {i}")
        with pytest.raises(ValueError):
            t.add_search("one too many")

    def test_seen_links_are_remembered_deduplicated_and_bounded(self):
        t = Tracker().mark_seen(["https://a.example/1", "https://a.example/2", "https://a.example/1"])
        assert t.seen == ["https://a.example/1", "https://a.example/2"]
        t = t.mark_seen([f"https://b.example/{i}" for i in range(1200)])
        assert len(t.seen) == 1000 and t.seen[-1] == "https://b.example/1199" and "https://a.example/1" not in t.seen

    def test_unsafe_links_are_skipped_instead_of_raising(self):
        t = Tracker().mark_seen(["javascript:alert(1)", "", "https://ok.example/1", "data:text/html,x"])
        assert t.seen == ["https://ok.example/1"]

    def test_searches_and_seen_links_survive_the_profile_file(self):
        t, _ = Tracker().add_search("Data Engineer", remote_only=True)
        t = t.mark_seen(["https://a.example/1"])
        _, loaded = load_file(dump_file(Profile(name="A B"), t))
        assert loaded.saved_searches[0].query == "Data Engineer" and loaded.seen == ["https://a.example/1"]

    def test_an_unused_tracker_adds_nothing_to_the_file(self):
        assert set(json.loads(dump_file(Profile(name="A B"), Tracker()))) == {"kind", "schema_version", "profile"}
        t, _ = Tracker().add_search("x")
        assert set(json.loads(dump_file(Profile(name="A B"), t))) == {
            "kind",
            "schema_version",
            "profile",
            "saved_searches",
        }

    def test_old_files_without_the_new_fields_still_load(self):
        old = json.loads(dump_file(Profile(name="A B"), Tracker().add("A", "B", on=D)[0]))
        for a in old["applications"]:
            for k in ("source", "contact", "next_action", "next_action_on"):
                a.pop(k, None)
        _, loaded = load_file(json.dumps(old))
        assert loaded.applications[0].source == "" and loaded.saved_searches == [] and loaded.seen == []

    @pytest.mark.parametrize("key", ["saved_searches", "seen"])
    def test_malformed_new_sections_are_rejected_with_a_message(self, key):
        data = json.loads(dump_file(Profile(name="A B")))
        data[key] = "nope"
        with pytest.raises(ProfileError, match=key):
            load_file(json.dumps(data))

    def test_hostile_values_are_rejected_or_cleaned(self):
        data = json.loads(dump_file(Profile(name="A B")))
        data["seen"] = ["javascript:alert(1)"]
        with pytest.raises(ProfileError):
            load_file(json.dumps(data))
        with pytest.raises(ValueError):
            Tracker().add("Acme", "Dev", on=D, contact="x" * 500)  # longer than the field allows
        _, a = Tracker().add("Acme", "Dev", on=D, source="Line\x07 one")
        assert "\x07" not in a.source
