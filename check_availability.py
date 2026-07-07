"""
Tidal River Campground availability watcher.

Checks Parks Victoria's live booking API (the same one the booking page itself
calls) for the date range 3 Jan - 10 Jan 2027, and sends a push notification
via ntfy.sh the moment any site shows availability.

This is designed to run on a schedule via GitHub Actions (see
.github/workflows/check.yml) - no server or always-on computer needed.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# --- Configuration -----------------------------------------------------

OPERATOR_ID = 33314          # Tidal River Campground's ID in the booking system
CONTROL_ID = 114
START_DATE = "2027-01-03"    # matches the API call the live site makes
QTY_OF_DATES = 14            # fetch 14 days starting from START_DATE
CHECK_UNTIL_DATE = "2027-01-10"  # only alert for dates within your window

# The ntfy topic name is read from an environment variable (set from a GitHub
# encrypted secret in the workflow) rather than being written here in plain
# text. This repo is public, so anything hardcoded here would be visible to
# anyone - keeping the topic name in a secret means nobody else can see it or
# subscribe to your alerts, even though the code itself is public.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
if not NTFY_TOPIC:
    sys.exit(
        "NTFY_TOPIC environment variable is not set. Add it as a repository "
        "secret (Settings -> Secrets and variables -> Actions) named NTFY_TOPIC."
    )

STATE_FILE = "state.json"

API_URL = (
    "https://webapi.bookeasy.com.au/api/getProductAvailabilityPreview"
    f"?operatorId={OPERATOR_ID}&controlId={CONTROL_ID}&type=accom"
    f"&queryStartDate={START_DATE}&qtyOfDates={QTY_OF_DATES}&includeInternalProducts=false"
)

BOOKING_URL = "https://bookings.parks.vic.gov.au/tidal-river-campground#/accom/33314"


# --- Core logic ----------------------------------------------------------

def fetch_availability() -> dict:
    # Some headers are added to look like a normal browser request, since the
    # real booking page sends these automatically and the API may expect them.
    req = urllib.request.Request(
        API_URL,
        method="POST",
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://bookings.parks.vic.gov.au/tidal-river-campground",
            "Origin": "https://bookings.parks.vic.gov.au",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def find_available_sites(data: dict) -> list[str]:
    """Return a list of human-readable strings for any open sites/dates in our window."""
    found = []
    rows = data.get("ProductAvailabilityPreview", {}).get("Rows", [])
    for row in rows:
        name = row.get("Name", "Unknown site")
        for d in row.get("Dates", []):
            d_date = (d.get("Date") or "")[:10]
            if not d_date or d_date > CHECK_UNTIL_DATE:
                continue
            qty = d.get("QtyAvailableForReservation", 0) or 0
            if qty > 0:
                found.append(f"{name} - {d_date}: {qty} available")
    return found


def send_notification(message: str) -> None:
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        method="POST",
        headers={
            "Title": "Tidal River site available!",
            "Priority": "urgent",
            "Tags": "tent,camping",
        },
    )
    urllib.request.urlopen(req, timeout=15)


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"available": False}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def main() -> None:
    data = fetch_availability()
    found = find_available_sites(data)
    is_available_now = len(found) > 0

    prev_state = load_state()

    if is_available_now:
        message = (
            "Tidal River Campground has openings for 3-10 Jan 2027!\n"
            + "\n".join(found)
            + f"\n\nBook now: {BOOKING_URL}"
        )
        print(message)
        # Only push a notification when availability newly appears, so you
        # don't get pinged every 15 minutes for the same still-open site.
        if not prev_state.get("available"):
            send_notification(message)
        else:
            print("(Already notified for this - not sending again until it changes.)")
    else:
        print(f"No availability found for {START_DATE} - {CHECK_UNTIL_DATE}. Checked at "
              f"{datetime.now(timezone.utc).isoformat()}")

    save_state({
        "available": is_available_now,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    main()
