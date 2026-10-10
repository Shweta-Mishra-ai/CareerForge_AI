"""Application tracker: kanban-style job applications, kept in the user's own profile file (no server storage).

The file is the same envelope as a plain profile file with an extra `applications` list, so a plain
`Profile.from_json` still reads it (tested) and an older app simply ignores the tracker.
"""

from __future__ import annotations

import json
import secrets
from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, field_validator

from careerforge.models import (
    FILE_KIND,
    MAX_FILE_BYTES,
    SCHEMA_VERSION,
    Link,
    Profile,
    ProfileError,
    _describe,
    _Model,
    line,
    paragraph,
)
from careerforge.text import normalize_url

Status = Literal["saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"]
STATUSES: tuple[str, ...] = ("saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn")
TERMINAL = frozenset({"offer", "rejected", "withdrawn"})
FOLLOW_UP_DAYS = {"follow_up_1": 7, "follow_up_2": 14}
CLOSE_OUT_DAYS = 21
MAX_APPLICATIONS = 500
MAX_SAVED_SEARCHES = 20
MAX_SEEN = 1000  # job links already shown; the oldest are forgotten first


def _iso_date(value: str) -> str:
    if value == "":
        return value
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("Dates must look like 2026-10-31") from exc


IsoDate = Annotated[str, AfterValidator(_iso_date)]


class Event(_Model):
    on: IsoDate
    status: Status
    note: paragraph(300) = ""


class Application(_Model):
    id: str = Field(default_factory=lambda: secrets.token_hex(6), pattern=r"^[0-9a-f]{12}$")
    company: line(100) = ""
    role: line(150) = ""
    url: Link = ""
    status: Status = "saved"
    applied_on: IsoDate = ""
    notes: paragraph(1000) = ""
    source: line(60) = ""  # where the posting was found: "LinkedIn", "a referral from Asha"
    contact: line(100) = ""  # the recruiter or hiring manager, if you know one
    next_action: line(150) = ""  # "Send thank-you note"
    next_action_on: IsoDate = ""
    ats_score: int | None = Field(default=None, ge=0, le=100)
    followups_sent: list[Literal["follow_up_1", "follow_up_2"]] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list, max_length=100)

    @field_validator("followups_sent")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class FollowUp(BaseModel):
    model_config = ConfigDict(frozen=True)
    application_id: str
    company: str
    role: str
    kind: Literal["follow_up_1", "follow_up_2", "close_out"]
    due_on: str
    overdue_days: int


class ActionDue(BaseModel):
    model_config = ConfigDict(frozen=True)
    application_id: str
    company: str
    role: str
    action: str
    due_on: str
    overdue_days: int


class SavedSearch(_Model):
    id: str = Field(default_factory=lambda: secrets.token_hex(6), pattern=r"^[0-9a-f]{12}$")
    query: line(100) = ""
    location: line(60) = ""
    remote_only: bool = False
    boards: list[line(300)] = Field(default_factory=list, max_length=10)  # pasted company careers-page links


class Tracker(_Model):
    applications: list[Application] = Field(default_factory=list, max_length=MAX_APPLICATIONS)
    saved_searches: list[SavedSearch] = Field(default_factory=list, max_length=MAX_SAVED_SEARCHES)
    seen: list[Link] = Field(default_factory=list, max_length=MAX_SEEN)

    def _with(self, **changes: object) -> Tracker:
        return Tracker.model_validate({**self.model_dump(), **changes})

    def add_search(
        self, query: str, *, location: str = "", remote_only: bool = False, boards: list[str] | None = None
    ) -> tuple[Tracker, SavedSearch]:
        """(tracker, search). The same query + location + remote setting is stored once; saving it again updates it."""
        new = SavedSearch(query=query, location=location, remote_only=remote_only, boards=boards or [])
        if not new.query:
            raise ValueError("A saved search needs a search phrase")

        def same(other: SavedSearch) -> bool:
            return (other.query.lower(), other.location.lower(), other.remote_only) == (
                new.query.lower(),
                new.location.lower(),
                new.remote_only,
            )

        existing = next((o for o in self.saved_searches if same(o)), None)
        if existing is None:
            return self._with(saved_searches=[*(o.model_dump() for o in self.saved_searches), new.model_dump()]), new
        kept = new.model_copy(update={"id": existing.id})
        return self._with(
            saved_searches=[(kept if o.id == existing.id else o).model_dump() for o in self.saved_searches]
        ), kept

    def remove_search(self, search_id: str) -> Tracker:
        return self._with(saved_searches=[s.model_dump() for s in self.saved_searches if s.id != search_id])

    def mark_seen(self, urls: list[str]) -> Tracker:
        """Remember job links so the next search can show only what is new. Keeps the newest MAX_SEEN."""
        valid = []
        for url in urls:
            try:
                if clean := normalize_url(url):
                    valid.append(clean)
            except ValueError:
                continue  # an unsafe or malformed link is simply not remembered
        merged = list(dict.fromkeys([*self.seen, *valid]))
        return self._with(seen=merged[-MAX_SEEN:])

    def get(self, app_id: str) -> Application:
        for a in self.applications:
            if a.id == app_id:
                return a
        raise KeyError(f"No application with id {app_id}")

    def add(
        self,
        company: str,
        role: str,
        *,
        url: str = "",
        status: Status = "saved",
        on: date | None = None,
        ats_score: int | None = None,
        notes: str = "",
        source: str = "",
        contact: str = "",
    ) -> tuple[Tracker, Application]:
        on = on or date.today()
        app = Application(
            company=company,
            role=role,
            url=url,
            status=status,
            notes=notes,
            source=source,
            contact=contact,
            ats_score=ats_score,
            applied_on=on.isoformat() if status == "applied" else "",
            events=[Event(on=on.isoformat(), status=status, note="added")],
        )
        return self._with(applications=[*(a.model_dump() for a in self.applications), app.model_dump()]), app

    def _replace(self, app: Application) -> Tracker:
        return self._with(applications=[(app if a.id == app.id else a).model_dump() for a in self.applications])

    def update(self, app_id: str, **fields: object) -> Tracker:
        if "id" in fields or "events" in fields or "status" in fields:
            raise ValueError("Use move() to change status; id and events are managed by the tracker")
        data = self.get(app_id).model_dump() | fields
        return self._replace(Application.model_validate(data))

    def move(self, app_id: str, status: Status, *, on: date | None = None, note: str = "") -> Tracker:
        on = on or date.today()
        app = self.get(app_id)
        data = app.model_dump()
        data["status"] = status
        if status == "applied" and not data["applied_on"]:
            data["applied_on"] = on.isoformat()
        data["events"] = [*data["events"], {"on": on.isoformat(), "status": status, "note": note}]
        return self._replace(Application.model_validate(data))

    def mark_followup_sent(self, app_id: str, kind: Literal["follow_up_1", "follow_up_2"]) -> Tracker:
        app = self.get(app_id)
        return self._replace(app.model_copy(update={"followups_sent": [*app.followups_sent, kind]}))

    def remove(self, app_id: str) -> Tracker:
        self.get(app_id)
        return self._with(applications=[a.model_dump() for a in self.applications if a.id != app_id])

    def actions_due(self, today: date | None = None) -> list[ActionDue]:
        """Next actions the user set for themselves that are due (or overdue) on applications still open."""
        today = today or date.today()
        out = []
        for a in self.applications:
            if not (a.next_action and a.next_action_on) or a.status in TERMINAL:
                continue
            due = date.fromisoformat(a.next_action_on)
            if due <= today:
                out.append(ActionDue(application_id=a.id, company=a.company, role=a.role, action=a.next_action,
                                     due_on=a.next_action_on, overdue_days=(today - due).days))  # fmt: skip
        return sorted(out, key=lambda x: (-x.overdue_days, x.company))

    def by_status(self) -> dict[str, list[Application]]:
        return {s: [a for a in self.applications if a.status == s] for s in STATUSES}

    def due(self, today: date | None = None) -> list[FollowUp]:
        """Follow-ups to send (day 7, day 14) and when to stop waiting (day 21), for applications still 'applied'."""
        today = today or date.today()
        out: list[FollowUp] = []
        for a in self.applications:
            if a.status != "applied" or not a.applied_on:
                continue
            sent = date.fromisoformat(a.applied_on)
            checkpoints = [(k, d) for k, d in FOLLOW_UP_DAYS.items() if k not in a.followups_sent]
            for kind, days in [*checkpoints, ("close_out", CLOSE_OUT_DAYS)]:
                due = sent + timedelta(days=days)
                if due <= today:
                    out.append(
                        FollowUp(
                            application_id=a.id,
                            company=a.company,
                            role=a.role,
                            kind=kind,  # type: ignore[arg-type]
                            due_on=due.isoformat(),
                            overdue_days=(today - due).days,
                        )
                    )
        return sorted(out, key=lambda f: (-f.overdue_days, f.company))


def dump_file(profile: Profile, tracker: Tracker | None = None, *, indent: int | None = 2) -> str:
    envelope = {"kind": FILE_KIND, "schema_version": SCHEMA_VERSION, "profile": profile.model_dump(mode="json")}
    if tracker:
        data = tracker.model_dump(mode="json")
        for key in ("applications", "saved_searches", "seen"):  # only what is used, so older files stay unchanged
            if data[key]:
                envelope[key] = data[key]
    return json.dumps(envelope, indent=indent, ensure_ascii=False)


def load_file(data: str | bytes) -> tuple[Profile, Tracker]:
    """Load a profile file plus its tracker (empty if the file has none). Raises ProfileError."""
    profile = Profile.from_json(data)  # validates size, kind, version and the profile itself
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_FILE_BYTES:  # from_json already enforced this; keep the guarantee local and explicit
        raise ProfileError("Profile file is too large")
    envelope = json.loads(raw.decode("utf-8-sig"))
    fields: dict[str, list] = {}
    for key in ("applications", "saved_searches", "seen"):
        value = envelope.get(key, [])
        if not isinstance(value, list):
            raise ProfileError(f"{key}: must be a list")
        fields[key] = value
    try:
        return profile, Tracker.model_validate(fields)
    except ValidationError as exc:
        raise ProfileError(_describe(exc)) from exc
