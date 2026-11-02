from __future__ import annotations

import re
from typing import Any

import httpx
import lxml.html

API = "https://api.holdsport.dk/v1"
WEB = "https://www.holdsport.dk"

# The reasons the website offers when you decline. Any text is accepted.
DECLINE_REASONS = ("Syg", "Skadet", "Ferie", "Skole", "Arbejde", "Sport", "Andet")

JOINED = 1  # "Tilmeld"
DECLINED = 2  # "Afmeld"


class HoldsportError(RuntimeError):
    pass


class Holdsport:
    """A Holdsport user. Pass the username (or email) and password you log in with."""

    def __init__(self, username: str, password: str, timeout: float = 20.0):
        self._auth = (username, password)
        self._api = httpx.Client(
            base_url=API, auth=self._auth, timeout=timeout, headers={"Accept": "application/json"}
        )
        self._web: httpx.Client | None = None
        self._timeout = timeout

    def close(self) -> None:
        self._api.close()
        if self._web is not None:
            self._web.close()

    def __enter__(self) -> Holdsport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- reading (API) ----

    def _get(self, path: str) -> Any:
        r = self._api.get(path)
        if r.status_code != 200:
            raise HoldsportError(f"GET {path}: HTTP {r.status_code}")
        return r.json()

    def teams(self) -> list[dict]:
        """Teams the user belongs to: id, name, role."""
        return self._get("/teams")

    def activities(self, team_id: int) -> list[dict]:
        """Upcoming activities of a team.

        Each has id, name, starttime, endtime, place, comment, event_type, activities_users
        (who answered and how) and no_rsvp (who has not answered yet)."""
        return self._get(f"/teams/{team_id}/activities")

    def members(self, team_id: int) -> list[dict]:
        return self._get(f"/teams/{team_id}/members")

    def unanswered(self, team_id: int, user_id: int) -> list[dict]:
        """Activities this user has not answered yet."""
        return [a for a in self.activities(team_id) if any(u.get("id") == user_id for u in a.get("no_rsvp", []))]

    # ---- answering ----

    def join(self, activity_id: int, user_id: int) -> None:
        """Sign up for an activity ("Tilmeld").

        The API sets a first answer. Once a user has answered, the API still returns 201 but
        ignores the change, so in that case the website's own form is used instead."""
        r = self._api.post(
            f"/activities/{activity_id}/activities_users",
            json={"activities_user": {"user_id": user_id, "picked": 1, "joined_status": JOINED}},
        )
        if r.status_code not in (200, 201):
            raise HoldsportError(f"join {activity_id}: HTTP {r.status_code}")
        if r.json().get("status_code") == JOINED:
            return
        web = self._login()
        page = web.get(f"/activities/{activity_id}")
        m = re.search(
            rf'<form[^>]+action="(/activities/{activity_id}/activities_users/\d+)"(.*?)</form>', page.text, re.S
        )
        token = _token(m.group(2), "authenticity_token") if m else None
        if not m or not token:
            raise HoldsportError(f"join {activity_id}: no answer form on the activity page")
        r = web.post(
            m.group(1),
            data={"utf8": "✓", "_method": "put", "authenticity_token": token, "activities_user[joined_status]": JOINED},
        )
        # The site has answered this request with HTTP 500 while still saving it, so the
        # page is read back instead of trusting the status code.
        self._expect(activity_id, "attending", f"join {activity_id}: HTTP {r.status_code}, still not signed up")

    def decline(self, activity_id: int, reason: str) -> None:
        """Decline an activity ("Afmeld") with a reason, as the website requires.

        The API has no route for this, so it goes through the website with a session login."""
        if not reason.strip():
            raise ValueError("Holdsport requires a reason to decline")
        web = self._login()
        page = web.get(f"/activities/{activity_id}")
        token = _token(page.text, "authenticity_token") or _meta_token(page.text)
        if page.status_code != 200 or not token:
            raise HoldsportError(f"decline {activity_id}: activity page HTTP {page.status_code}")
        r = web.post(
            f"/activities/{activity_id}/unattends",
            data={"utf8": "✓", "authenticity_token": token, "unattend_reason": reason},
            headers={"X-CSRF-Token": token},
        )
        self._expect(activity_id, "not_attending", f"decline {activity_id}: HTTP {r.status_code}, still not declined")

    def _expect(self, activity_id: int, state: str, error: str) -> None:
        page = self._login().get(f"/activities/{activity_id}").text
        if f"<div class='{state} choice'>" not in page:
            raise HoldsportError(error)

    def status(self, team_id: int, activity_id: int, user_id: int) -> str | None:
        """The user's current answer on an activity, e.g. "Tilmeldt" or "Afmeldt"; None if unanswered."""
        for a in self.activities(team_id):
            if a.get("id") == activity_id:
                for u in a.get("activities_users", []):
                    if u.get("user_id") == user_id:
                        return u.get("status")
                return None
        raise HoldsportError(f"activity {activity_id} not found in team {team_id}")

    # ---- messages (website only: the API has none) ----

    def messages(self) -> list[dict]:
        """The message center: id, sender, when (as shown, e.g. "3. nov"), subject, text.
        Reading the page does not mark anything read."""
        doc = lxml.html.fromstring(self._login().get("/message_center").text)
        out = []
        for row in doc.find_class("message_row"):
            out.append(
                {
                    "id": row.get("phx-value-id") or "",
                    "sender": _text(row, "sender"),
                    "when": _text(row, "timestamp"),
                    "subject": _text(row, "subject"),
                    "text": _text(row, "message"),
                    "unread": "unread" in (row.get("class") or "").split(),
                }
            )
        return out

    def chat_rooms(self) -> list[dict]:
        """Every chat room with its latest message: id, name, when (as shown), last ("Author: text"),
        unread. The full history of a room is only on the page's live socket, not here."""
        doc = lxml.html.fromstring(self._login().get("/chat").text)
        out = []
        for row in doc.find_class("chat_room_row"):
            last = [m.text_content().strip() for m in row.find_class("chat_room_message")]
            out.append(
                {
                    "id": row.get("phx-value-id") or "",
                    "name": _text(row, "chat_room_name"),
                    "when": _text(row, "timestamp"),
                    "last": next((m for m in last if m), ""),
                    "unread": "unread" in (row.get("class") or "").split() or bool(row.find_class("unread")),
                }
            )
        return out

    # ---- website session ----

    def _login(self) -> httpx.Client:
        if self._web is not None:
            return self._web
        web = httpx.Client(
            base_url=WEB, timeout=self._timeout, follow_redirects=True, headers={"Accept": "text/html,application/xhtml+xml"}
        )
        front = web.get("/")
        token = _token(front.text, "_csrf_token") or _meta_token(front.text)
        if not token:
            raise HoldsportError("login: no CSRF token on the front page")
        r = web.post(
            "/sessions",
            data={
                "_csrf_token": token,
                "session[username]": self._auth[0],
                "session[password]": self._auth[1],
                "session[remember_me]": "0",
            },
        )
        if "/sign_out" not in r.text:
            raise HoldsportError("login: website did not accept the username and password")
        self._web = web
        return web


def _text(el: Any, cls: str) -> str:
    found = el.find_class(cls)
    return " ".join(found[0].text_content().split()) if found else ""


def _token(html: str, name: str) -> str | None:
    m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]+)"', html) or re.search(
        rf'value="([^"]+)"[^>]*name="{re.escape(name)}"', html
    )
    return m.group(1) if m else None


def _meta_token(html: str) -> str | None:
    m = re.search(r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', html) or re.search(
        r'<meta[^>]+content="([^"]+)"[^>]+name="csrf-token"', html
    )
    return m.group(1) if m else None
