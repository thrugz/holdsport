# holdsport

A small Python client for [Holdsport](https://www.holdsport.dk), the app many Danish sports clubs use for training, matches and sign-ups.

Holdsport has no public, documented API. This client uses what an ordinary user login can reach, so it works for any member, coach or parent who can log in to the app. Nothing here needs admin rights or an agreement with Holdsport.

## What it can do

| Task | How | Route |
|---|---|---|
| List your teams | `teams()` | API |
| List a team's upcoming activities, with who has and has not answered | `activities(team_id)` | API |
| List a team's members | `members(team_id)` | API |
| Find activities you have not answered | `unanswered(team_id, user_id)` | API |
| Sign up ("Tilmeld") | `join(activity_id, user_id)` | API, or the website if you already answered |
| Decline ("Afmeld") with a reason | `decline(activity_id, reason)` | website |
| Read your current answer | `status(team_id, activity_id, user_id)` | API |

## Install

```sh
pip install git+https://github.com/thrugz/holdsport.git
```

Python 3.10 or newer. The only dependency is `httpx`.

## Use

```python
import os
from holdsport import Holdsport

with Holdsport(os.environ["HOLDSPORT_USER"], os.environ["HOLDSPORT_PASSWORD"]) as hs:
    team = hs.teams()[0]
    me = next(m for m in hs.members(team["id"]) if m["firstname"] == "Ori")

    for activity in hs.unanswered(team["id"], me["id"]):
        print(activity["starttime"], activity["name"], activity["place"])
        if activity["event_type"] == "Træning":
            hs.join(activity["id"], me["id"])
        else:
            hs.decline(activity["id"], "Arbejde")
```

Keep the login in environment variables or a secret store, never in code.

## How Holdsport works, as far as we found

Holdsport has two surfaces, and neither does everything.

**The JSON API** at `https://api.holdsport.dk/v1` uses HTTP Basic with your normal login. It is what the mobile app uses.

- `GET /teams`, `GET /teams/{id}/activities` and `GET /teams/{id}/members` work.
- `POST /activities/{id}/activities_users` with `{"activities_user": {"user_id": …, "picked": 1, "joined_status": 1}}` signs you up. `joined_status` 1 means signed up and 2 means declined.
- The API only records your **first** answer. Later changes still return `201`, but nothing changes, so a client has to check the result.
- An extra field in that body returns `500`.
- There is no API route for declining with a reason, for changing an answer, or for creating activities.

**The website** at `https://www.holdsport.dk` takes a session login (`POST /sessions` with the CSRF token from the front page).

- To decline, post `unattend_reason` to `/activities/{id}/unattends`. Holdsport requires a reason. The site suggests Syg, Skadet, Ferie, Skole, Arbejde, Sport and Andet, but free text works too.
- To change an answer back to signed up, post `activities_user[joined_status]=1` to `/activities/{id}/activities_users/{answer_id}` with `_method=put`. This can answer with HTTP `500` even though it saved the change, so the client reads the page back instead of trusting the status code.
- Ask for `text/html`. With a generic `Accept` header, an activity page comes back as an iCalendar file.

Both surfaces are undocumented and can change without notice. Every call raises `HoldsportError` when something does not look as expected, so you notice a change instead of failing silently.

## Calendar

If you only need to read the calendar, Holdsport also offers a personal ICS subscription link in the app. That link contains a personal token, so treat it like a password.

## Good manners

This uses your own account to do what you could do by hand in the app. Keep the volume at what a person would do, and do not use it to collect other members' data. Holdsport's user terms allow use of the service through the website and the app; they do not mention automated access either way.

## Status

Tested on 2 November 2026 against a test team: listing, signing up, declining with a reason, and switching back and forth.

Not affiliated with Holdsport ApS.

## About

Made by [Skarnlabs](https://skarnlabs.dk) in Denmark, shared for the Danish community.

## License

MIT
