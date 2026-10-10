import json

import pytest

from careerforge.models import (
    Certification,
    Contact,
    DateRange,
    Education,
    Experience,
    Profile,
    ProfileError,
    Project,
)


def make_profile(**over):
    base = dict(
        name="Priya Nair",
        headline="Senior Backend Engineer",
        summary="Backend engineer.",
        contact=Contact(
            email="priya@example.com",
            phone="+91 98765 43210",
            location="Bengaluru",
            linkedin="linkedin.com/in/priya",
            github="github.com/priya",
        ),
        skills=["python", "Node", "Python"],
        experience=[
            Experience(
                title="Engineer",
                company="Acme",
                dates=DateRange(start="Mar 2021", current=True),
                bullets=["• Cut latency 40%", ""],
            )
        ],
        education=[Education(degree="B.Tech", institution="NIT", dates=DateRange(end="2018"))],
        projects=[Project(name="Tool", description="A tool", tech=["react", "React"], url="github.com/priya/tool")],
        certifications=[Certification(name="AWS Developer", date="2022")],
    )
    base.update(over)
    return Profile(**base)


class TestNormalisation:
    def test_fields_are_cleaned_and_canonicalised(self):
        p = make_profile()
        assert p.skills == ["Python", "Node.js"]
        assert p.experience[0].bullets == ["Cut latency 40%"]
        assert p.experience[0].dates.start == "2021-03"
        assert p.projects[0].tech == ["React"]
        assert p.contact.linkedin == "https://linkedin.com/in/priya"

    def test_html_is_stored_verbatim_not_escaped(self):
        p = Profile(name="R&D <b>Lead</b>")
        assert p.name == "R&D <b>Lead</b>"

    def test_empty_profile_is_valid_draft(self):
        assert Profile().name == "" and Profile().skills == []

    @pytest.mark.parametrize(
        "field,value",
        [
            ("name", "x" * 121),
            ("summary", "x" * 1501),
            ("skills", ["x"] * 81),
        ],
    )
    def test_overlong_is_rejected_not_truncated(self, field, value):
        with pytest.raises(ValueError):
            Profile(**{field: value})

    def test_bad_contact_rejected_with_path(self):
        with pytest.raises(ValueError, match="email"):
            Profile(contact={"email": "nope"})

    def test_javascript_link_rejected(self):
        with pytest.raises(ValueError):
            Project(url="javascript:alert(1)")

    def test_linkedin_must_be_linkedin(self):
        with pytest.raises(ValueError):
            Contact(linkedin="https://evil.com/in/x")

    def test_unknown_field_rejected(self):
        with pytest.raises(ValueError):
            Profile(nmae="typo")

    def test_validate_assignment(self):
        p = Profile()
        with pytest.raises(ValueError):
            p.contact.email = "nope"


class TestDateRange:
    def test_end_before_start_rejected(self):
        with pytest.raises(ValueError, match="before"):
            DateRange(start="2022", end="2020")

    def test_year_only_same_year_ok(self):
        DateRange(start="2020", end="2020")

    def test_current_with_end_rejected(self):
        with pytest.raises(ValueError):
            DateRange(start="2020", end="2021", current=True)

    @pytest.mark.parametrize(
        "kwargs,want",
        [
            (dict(start="2021-03", current=True), "Mar 2021 – Present"),
            (dict(start="2019", end="2023"), "2019 – 2023"),
            (dict(end="2018"), "2018"),
            (dict(), ""),
        ],
    )
    def test_display(self, kwargs, want):
        assert DateRange(**kwargs).display() == want


class TestProvenance:
    def test_suggested_items_default_unconfirmed(self):
        assert Experience(origin="suggested").confirmed is False
        assert Experience(origin="extracted").confirmed is True
        assert Experience(origin="suggested", confirmed=True).confirmed is True

    def test_exportable_drops_unconfirmed_and_does_not_mutate(self):
        p = make_profile(
            experience=[
                Experience(title="Real", origin="user"),
                Experience(title="Invented freelance gig", origin="suggested"),
            ]
        )
        out = p.exportable()
        assert [e.title for e in out.experience] == ["Real"]
        assert len(p.experience) == 2

    def test_pending_items_listed(self):
        p = make_profile(projects=[Project(name="X", origin="suggested")])
        assert p.pending_items() == [("projects", 0, "X")]


class TestPersistence:
    def test_round_trip_is_lossless(self):
        p = make_profile()
        assert Profile.from_json(p.to_json()) == p

    def test_round_trip_preserves_hash_and_hash_tracks_content(self):
        p = make_profile()
        assert Profile.from_json(p.to_json()).content_hash() == p.content_hash()
        assert make_profile(name="Other Person").content_hash() != p.content_hash()

    def test_unicode_survives(self):
        p = Profile(name="Zoë Müller 张伟")
        assert Profile.from_json(p.to_json()).name == "Zoë Müller 张伟"

    def test_provenance_survives_round_trip(self):
        p = make_profile(projects=[Project(name="X", origin="suggested")])
        assert Profile.from_json(p.to_json()).projects[0].confirmed is False

    @pytest.mark.parametrize(
        "payload,msg",
        [
            ("not json", "not valid JSON"),
            ("[1,2]", "not a CareerForge"),
            ('{"kind":"other","schema_version":1,"profile":{}}', "not a CareerForge"),
            ('{"kind":"careerforge.profile","profile":{}}', "schema_version"),
            ('{"kind":"careerforge.profile","schema_version":true,"profile":{}}', "schema_version"),
            ('{"kind":"careerforge.profile","schema_version":99,"profile":{}}', "newer version"),
            ('{"kind":"careerforge.profile","schema_version":1}', "no profile"),
            ('{"kind":"careerforge.profile","schema_version":1,"profile":{"contact":{"email":"x"}}}', "contact.email"),
        ],
    )
    def test_bad_files_give_clear_errors(self, payload, msg):
        with pytest.raises(ProfileError, match=msg):
            Profile.from_json(payload)

    def test_oversize_rejected(self):
        with pytest.raises(ProfileError, match="too large"):
            Profile.from_json(b" " * 2_000_001)

    def test_invalid_utf8_rejected(self):
        with pytest.raises(ProfileError):
            Profile.from_json(b"\xff\xfe\x00")

    def test_bom_tolerated(self):
        assert Profile.from_json(b"\xef\xbb\xbf" + make_profile().to_json().encode()).name == "Priya Nair"

    def test_envelope_shape(self):
        env = json.loads(make_profile().to_json())
        assert env["kind"] == "careerforge.profile" and env["schema_version"] == 1
