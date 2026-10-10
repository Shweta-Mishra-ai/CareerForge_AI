"""LinkedIn data-export reader. The CSV layout is built from our understanding of LinkedIn's format (no real
export was available), so these tests pin OUR parser's behaviour; verify against a real export before relying on it."""

import zipfile

import pytest
from helpers import zip_bytes

from careerforge.ingest.errors import IngestError, UnreadableDocument
from careerforge.ingest.linkedin import profile_from_linkedin_export

PROFILE = b'First Name,Last Name,Maiden Name,Address,Birth Date,Headline,Summary,Industry,Zip Code,Geo Location,Twitter Handles,Websites,Instant Messengers\nPriya,Nair,,,,Senior Backend Engineer,"Backend engineer.\nBuilds payment APIs.",Software,,"Bengaluru, Karnataka, India",,[PERSONAL:https://priya.dev],\n'
POSITIONS = b'Company Name,Title,Description,Location,Started On,Finished On\nFinlytics,Senior Backend Engineer,"Designed settlement service handling 2M transactions/day.\n- Cut p95 latency 480ms to 190ms using Redis.","Bengaluru, India",Mar 2021,\nShipFast,Software Engineer,Built real-time tracking APIs.,Pune,Jul 2018,Feb 2021\n'
EDUCATION = b"School Name,Start Date,End Date,Notes,Degree Name,Activities\nNIT Calicut,2014,2018,Dean's list,B.Tech Computer Science,Robotics club\n"
SKILLS = b"Name\nPython\nkubernetes\nPython\n"
CERTS = b"Name,Url,Authority,Started On,Finished On,License Number\nAWS Certified Developer - Associate,https://aws.amazon.com/cert/x,Amazon Web Services,Jun 2022,,ABC123\n"
EMAILS = b"Email Address,Confirmed,Primary,Updated On\nold@example.org,Yes,No,2020\npriya@gmail.com,Yes,Yes,2024\n"
PHONES = b"Extension,Number,Type\n,+91 98765 43210,Mobile\n"

FULL = {"Basic_LinkedInDataExport/Profile.csv": PROFILE, "Positions.csv": POSITIONS, "Education.csv": EDUCATION,
        "Skills.csv": SKILLS, "Certifications.csv": CERTS, "Email Addresses.csv": EMAILS, "PhoneNumbers.csv": PHONES}  # fmt: skip


def load(files=None):
    return profile_from_linkedin_export(zip_bytes(files or FULL))


def test_full_export_maps_to_a_profile():
    r = load()
    p = r.profile
    assert (p.name, p.headline) == ("Priya Nair", "Senior Backend Engineer")
    assert p.summary == "Backend engineer.\nBuilds payment APIs."
    assert (p.contact.email, p.contact.phone, p.contact.location) == (
        "priya@gmail.com",
        "+91 98765 43210",
        "Bengaluru, Karnataka, India",
    )
    assert p.contact.website == "https://priya.dev"
    assert p.skills == ["Python", "Kubernetes"]  # deduped + canonicalised
    cur, old = p.experience
    assert (cur.title, cur.company) == (
        "Senior Backend Engineer",
        "Finlytics",
    ) and cur.dates.display() == "Mar 2021 – Present"
    assert old.dates.display() == "Jul 2018 – Feb 2021"
    assert cur.bullets == [
        "Designed settlement service handling 2M transactions/day.",
        "Cut p95 latency 480ms to 190ms using Redis.",
    ]
    edu = p.education[0]
    assert (
        edu.degree == "B.Tech Computer Science"
        and edu.dates.display() == "2014 – 2018"
        and "Activities: Robotics club" in edu.details
    )
    assert p.certifications[0].issuer == "Amazon Web Services" and p.certifications[0].date == "2022-06"
    assert r.warnings == () and "positions.csv" in r.files_used


def test_primary_email_wins_over_first():
    assert load().profile.contact.email == "priya@gmail.com"


def test_ongoing_study_is_not_marked_as_a_current_job():
    edu = b"School Name,Start Date,End Date,Notes,Degree Name,Activities\nIIT,2023,,,M.Tech,\n"
    e = load({"Education.csv": edu}).profile.education[0]
    assert e.dates.current is False and e.dates.start == "2023" and e.dates.end == ""


def test_hyphenated_text_is_not_split_and_long_text_is_split_not_dropped():
    long = ("Sentence number one is here. " * 40).strip()
    pos = f'Company Name,Title,Description,Location,Started On,Finished On\nAcme,Dev,"Built full-stack real-time apps. {long}",,2020,\n'.encode()
    bullets = load({"Positions.csv": pos}).profile.experience[0].bullets
    assert bullets[0].startswith("Built full-stack real-time apps.") and all(len(b) <= 600 for b in bullets)
    assert "".join(bullets).count("Sentence number one") == 40  # nothing lost


def test_notes_lines_above_header_and_bom_tolerated():
    csv_ = b"\xef\xbb\xbfNotes:\nThis file may have extra lines\n\nCompany Name,Title,Description,Location,Started On,Finished On\nAcme,Dev,,,2020,2021\n"
    assert load({"Positions.csv": csv_}).profile.experience[0].company == "Acme"


def test_header_case_and_column_order_do_not_matter():
    csv_ = b"TITLE,started on,COMPANY NAME,Finished On\nDev,Jan 2020,Acme,Dec 2021\n"
    e = load({"Positions.csv": csv_}).profile.experience[0]
    assert (e.title, e.company, e.dates.display()) == ("Dev", "Acme", "Jan 2020 – Dec 2021")


def test_missing_files_just_mean_missing_sections():
    p = load({"Skills.csv": SKILLS}).profile
    assert p.skills == ["Python", "Kubernetes"] and p.experience == []


def test_unreadable_dates_warn_and_keep_the_item():
    pos = b"Company Name,Title,Description,Location,Started On,Finished On\nAcme,Dev,,,sometime,\n"
    r = load({"Positions.csv": pos})
    assert (
        r.profile.experience[0].company == "Acme"
        and r.profile.experience[0].dates.is_empty()
        and "dates" in r.warnings[0]
    )


def test_overlong_field_is_shortened_with_a_warning():
    pos = (
        "Company Name,Title,Description,Location,Started On,Finished On\n" + "Acme," + "T" * 400 + ",,,2020,\n"
    ).encode()
    r = load({"Positions.csv": pos})
    assert len(r.profile.experience[0].title) == 150 and "shortened" in r.warnings[0]


def test_too_many_skills_warns():
    skills = ("Name\n" + "\n".join(f"Skill{i}" for i in range(120))).encode()
    r = load({"Skills.csv": skills})
    assert len(r.profile.skills) == 80 and "only the first 80" in r.warnings[0]


def test_private_files_are_never_opened(monkeypatch):
    private = {"messages.csv": b"CONTENT,FROM\nSECRET MESSAGE,Boss\n", "Connections.csv": b"First Name\nAlice\n",
               "Invitations.csv": b"x\ny\n", "Ad_Targeting.csv": b"x\ny\n", "Receipts_v2.csv": b"x\ny\n"}  # fmt: skip
    archive = zip_bytes({**FULL, **private})  # build BEFORE spying: writestr() itself calls ZipFile.open(mode="w")
    opened = []
    real = zipfile.ZipFile.open

    def spy(self, name, *a, **kw):
        opened.append((name.filename if hasattr(name, "filename") else name).lower().split("/")[-1])
        return real(self, name, *a, **kw)

    monkeypatch.setattr(zipfile.ZipFile, "open", spy)
    r = profile_from_linkedin_export(archive)
    assert "positions.csv" in opened, "positive control: the spy must see the allow-listed reads"
    assert not {n.lower() for n in private} & set(opened)
    assert "messages.csv" not in r.files_used and "SECRET" not in r.profile.model_dump_json()


@pytest.mark.parametrize("files", [{"readme.txt": b"hi"}, {"Messages.csv": b"a\nb\n"}, {}])
def test_zip_that_is_not_a_linkedin_export(files):
    with pytest.raises(IngestError, match="does not look like"):
        profile_from_linkedin_export(zip_bytes(files)) if files else profile_from_linkedin_export(
            zip_bytes({"x.txt": b"y"})
        )


def test_corrupt_zip_and_oversize_entry_and_zip_bomb():
    with pytest.raises(UnreadableDocument):
        profile_from_linkedin_export(b"PK\x03\x04 broken")
    with pytest.raises(UnreadableDocument, match="unusually large"):
        profile_from_linkedin_export(zip_bytes({"Positions.csv": b"Title\n" + b"a" * 6_000_000}))
    with pytest.raises(UnreadableDocument, match="too many files"):
        profile_from_linkedin_export(zip_bytes({f"f{i}.txt": b"x" for i in range(600)}))


def test_hostile_values_are_stored_inertly():
    pos = b'Company Name,Title,Description,Location,Started On,Finished On\n"<script>alert(1)</script>","=cmd|calc",<img src=x onerror=alert(1)>,,2020,\n'
    e = load({"Positions.csv": pos}).profile.experience[0]
    assert e.company == "<script>alert(1)</script>" and e.title == "=cmd|calc"  # raw text; escaped only at render time


def test_path_traversal_names_are_harmless():
    r = load({"../../Positions.csv": POSITIONS, "..\\Skills.csv": SKILLS})
    assert r.profile.experience and r.profile.skills
