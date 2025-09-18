import argparse
import base64
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib import error, parse, request
from zoneinfo import ZoneInfo

API_BASE_URL = "https://api.planningcenteronline.com/services/v2/service_types/1069223/plans"
APP_ID_ENV = "PLANNING_CENTER_APP_ID"
SECRET_ENV = "PLANNING_CENTER_SECRET"
PLAN_ID: Optional[str] = None
PLAN_TIMES: Dict[str, str] = {}
PLAN_ITEMS_BY_TIME: Dict[str, List[Dict[str, object]]] = {}
UTC_ZONE = ZoneInfo("UTC")
CENTRAL_ZONE = ZoneInfo("America/Chicago")


def valid_date(value: str) -> str:
    """Ensure the provided value matches YYYY-MM-DD."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Date must be in YYYY-MM-DD format"
        ) from exc
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetches the first plan after the provided date and its related data."
    )
    parser.add_argument(
        "after_date",
        type=valid_date,
        help="Date in YYYY-MM-DD format used for the Planning Center 'after' filter.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format: 'text' (default) or 'json'.",
    )
    return parser.parse_args()


def get_credentials() -> tuple[str, str]:
    app_id = os.environ.get(APP_ID_ENV)
    secret = os.environ.get(SECRET_ENV)
    if not app_id or not secret:
        missing = []
        if not app_id:
            missing.append(APP_ID_ENV)
        if not secret:
            missing.append(SECRET_ENV)
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )
    return app_id, secret


def build_url(after_date: str) -> str:
    params = {
        "per_page": "1",
        "filter": "after",
        "after": after_date,
    }
    query = parse.urlencode(params)
    return f"{API_BASE_URL}?{query}"


def build_plan_times_url(plan_id: str) -> str:
    return f"{API_BASE_URL}/{plan_id}/plan_times"


def build_plan_items_url(plan_id: str) -> str:
    return f"{API_BASE_URL}/{plan_id}/items?include=item_times"


def build_request(url: str, app_id: str, secret: str) -> request.Request:
    credentials = f"{app_id}:{secret}".encode("utf-8")
    encoded_credentials = base64.b64encode(credentials).decode("ascii")
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Accept": "application/json",
        "User-Agent": "planning-center-integration/0.1",
    }
    return request.Request(url, headers=headers)


def fetch_json(url: str, context: str) -> dict:
    app_id, secret = get_credentials()
    req = build_request(url, app_id, secret)

    try:
        with request.urlopen(req) as response:
            payload = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{context} request failed with status {exc.code}: {body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Failed to reach API for {context}: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{context} response was not valid JSON") from exc


def fetch_plan(after_date: str) -> dict:
    url = build_url(after_date)
    data = fetch_json(url, "Plan")

    global PLAN_ID
    try:
        PLAN_ID = str(data["data"][0]["id"])
    except (KeyError, IndexError, TypeError):
        PLAN_ID = None

    return data


def fetch_plan_times(plan_id: str) -> dict:
    url = build_plan_times_url(plan_id)
    return fetch_json(url, "Plan times")


def fetch_plan_items(plan_id: str) -> dict:
    url = build_plan_items_url(plan_id)
    return fetch_json(url, "Plan items")


def fetch_item_time_detail(base_url: str, item_time_id: str) -> dict:
    url = f"{base_url.rstrip('/')}/{item_time_id}"
    return fetch_json(url, "Item time")


def to_central_iso(timestamp: str) -> Optional[str]:
    """Convert an ISO8601 timestamp to America/Chicago time."""
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC_ZONE)

    try:
        converted = parsed.astimezone(CENTRAL_ZONE)
    except ValueError:
        return None
    return converted.isoformat()


def stash_service_times(plan_times: dict) -> None:
    global PLAN_TIMES
    PLAN_TIMES = {}

    entries = plan_times.get("data")
    if not isinstance(entries, list):
        return

    for entry in entries:
        attributes = entry.get("attributes") if isinstance(entry, dict) else None
        if not isinstance(attributes, dict):
            continue
        if attributes.get("time_type") != "service":
            continue

        starts_at = attributes.get("starts_at")
        plan_time_id = entry.get("id")
        if not (isinstance(plan_time_id, str) and isinstance(starts_at, str)):
            continue

        converted = to_central_iso(starts_at)
        PLAN_TIMES[plan_time_id] = converted or starts_at


def map_items_by_plan_time(plan_items: dict) -> None:
    global PLAN_ITEMS_BY_TIME
    PLAN_ITEMS_BY_TIME = {}

    items = plan_items.get("data")
    if not isinstance(items, list):
        return

    aggregated: Dict[str, List[Dict[str, object]]] = defaultdict(list)

    for item in items:
        if not isinstance(item, dict):
            continue
        relationships = item.get("relationships")
        if not isinstance(relationships, dict):
            continue
        item_times_rel = relationships.get("item_times")
        if not isinstance(item_times_rel, dict):
            continue

        refs = item_times_rel.get("data")
        if not isinstance(refs, list) or not refs:
            continue
        related_link = item_times_rel.get("links", {}).get("related")
        if not isinstance(related_link, str):
            continue

        for ref in refs:
            if not isinstance(ref, dict):
                continue
            item_time_id = ref.get("id")
            if not isinstance(item_time_id, str):
                continue

            detail = fetch_item_time_detail(related_link, item_time_id)
            plan_time_rel = (
                detail.get("data", {})
                .get("relationships", {})
                .get("plan_time", {})
                .get("data", {})
            )
            plan_time_id = plan_time_rel.get("id") if isinstance(plan_time_rel, dict) else None
            if not isinstance(plan_time_id, str):
                continue

            if PLAN_TIMES and plan_time_id not in PLAN_TIMES:
                continue

            attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            aggregated[plan_time_id].append(
                {
                    "item_id": item.get("id"),
                    "item_time_id": item_time_id,
                    "title": attributes.get("title"),
                    "sequence": attributes.get("sequence"),
                    "length": attributes.get("length"),
                }
            )

    PLAN_ITEMS_BY_TIME = dict(aggregated)


def parse_iso_timestamp(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def format_time_label(iso_timestamp: str) -> Tuple[Optional[datetime], str]:
    dt = parse_iso_timestamp(iso_timestamp)
    if dt is None:
        return None, iso_timestamp
    label = dt.strftime("%I:%M %p").lstrip("0")
    return dt, label


def _item_sequence_sort_key(item: Dict[str, object]) -> Tuple[int, int]:
    sequence = item.get("sequence")
    if isinstance(sequence, int):
        return (0, sequence)
    if isinstance(sequence, str):
        try:
            parsed = int(sequence)
            return (0, parsed)
        except ValueError:
            pass
    return (1, sys.maxsize)


def build_plan_schedule() -> List[Tuple[str, List[Dict[str, object]]]]:
    schedule: List[Tuple[Optional[datetime], str, List[Dict[str, object]]]] = []

    for plan_time_id, iso_time in PLAN_TIMES.items():
        items = PLAN_ITEMS_BY_TIME.get(plan_time_id)
        if not items:
            continue

        dt, label = format_time_label(iso_time)
        sorted_items = sorted(
            (item for item in items if isinstance(item, dict)),
            key=_item_sequence_sort_key,
        )
        simplified_items = []
        for index, item in enumerate(sorted_items, start=1):
            simplified_items.append(
                {
                    "title": item.get("title"),
                    "sequence": index,
                    "length": item.get("length"),
                }
            )
        schedule.append((dt, label, simplified_items))

    schedule.sort(key=lambda entry: (entry[0] is None, entry[0], entry[1]))

    return [(label, items) for _, label, items in schedule]


def print_json(schedule: List[Tuple[str, List[Dict[str, object]]]]) -> None:
    output = {
        "plan": [
            {
                "time": label,
                "items": items,
            }
            for label, items in schedule
        ]
    }
    print(json.dumps(output, indent=2))


def print_text(schedule: List[Tuple[str, List[Dict[str, object]]]]) -> None:
    lines: List[str] = []
    for label, items in schedule:
        lines.append(label)
        for item in items:
            sequence = item.get("sequence")
            length = item.get("length")
            title = item.get("title")
            seq_display = sequence if sequence is not None else "-"
            length_display = f"{length} seconds" if length is not None else "unknown length"
            lines.append(f"{seq_display}: {title} - {length_display}")
        lines.append("")
    print("\n".join(lines).rstrip())


def main() -> None:
    args = parse_args()

    try:
        fetch_plan(args.after_date)
        if PLAN_ID is None:
            raise RuntimeError("No plan ID returned; unable to fetch plan times.")
        plan_times = fetch_plan_times(PLAN_ID)
        stash_service_times(plan_times)
        plan_items = fetch_plan_items(PLAN_ID)
        map_items_by_plan_time(plan_items)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    schedule = build_plan_schedule()
    if args.format == "text":
        print_text(schedule)
    else:
        print_json(schedule)


if __name__ == "__main__":
    main()


