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

Status = Literal["saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn"]
STATUSES: tuple[str, ...] = ("saved", "applied", "screening", "interview", "offer", "rejected", "withdrawn")
TERMINAL = frozenset({"offer", "rejected", "withdrawn"})
FOLLOW_UP_DAYS = {"follow_up_1": 7, "follow_up_2": 14}
CLOSE_OUT_DAYS = 21
MAX_APPLICATIONS = 500


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


class Tracker(_Model):
    applications: list[Application] = Field(default_factory=list, max_length=MAX_APPLICATIONS)

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
    ) -> tuple[Tracker, Application]:
        on = on or date.today()
        app = Application(
            company=company,
            role=role,
            url=url,
            status=status,
            notes=notes,
            ats_score=ats_score,
            applied_on=on.isoformat() if status == "applied" else "",
            events=[Event(on=on.isoformat(), status=status, note="added")],
        )
        return Tracker(applications=[*self.applications, app]), app

    def _replace(self, app: Application) -> Tracker:
        return Tracker(applications=[app if a.id == app.id else a for a in self.applications])

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
        return Tracker(applications=[a for a in self.applications if a.id != app_id])

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
    if tracker and tracker.applications:
        envelope["applications"] = tracker.model_dump(mode="json")["applications"]
    return json.dumps(envelope, indent=indent, ensure_ascii=False)


def load_file(data: str | bytes) -> tuple[Profile, Tracker]:
    """Load a profile file plus its tracker (empty if the file has none). Raises ProfileError."""
    profile = Profile.from_json(data)  # validates size, kind, version and the profile itself
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_FILE_BYTES:  # from_json already enforced this; keep the guarantee local and explicit
        raise ProfileError("Profile file is too large")
    envelope = json.loads(raw.decode("utf-8-sig"))
    apps = envelope.get("applications", [])
    if not isinstance(apps, list):
        raise ProfileError("applications: must be a list")
    try:
        return profile, Tracker.model_validate({"applications": apps})
    except ValidationError as exc:
        raise ProfileError(_describe(exc)) from exc
