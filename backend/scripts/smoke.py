"""Check a deployed AqylRoute against the demo checklist. Read-only: nothing is created or changed.

Run from backend/ after `python seed.py --yes` on the production database:
    python scripts/smoke.py --api https://<app>.up.railway.app --web https://<app>.vercel.app

Exit code 1 if any check fails.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seed import DEMO_PASSWORD, DEMO_PHONE, demo_date  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' — {detail}' if detail and not ok else ''}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", required=True, help="backend URL (Railway)")
    parser.add_argument("--web", help="frontend URL (Vercel), for the page and CORS checks")
    parser.add_argument("--today", default=None, help="demo date for overdue (default: the seed's 11 September)")
    args = parser.parse_args()

    today = args.today or demo_date(date.today()).isoformat()
    api = httpx.Client(base_url=args.api.rstrip("/"), timeout=60)

    r = api.get("/health")
    check(r.status_code == 200 and r.json().get("status") == "ok", "backend /health", r.text[:200])

    r = api.get("/services")
    check(r.status_code == 200 and len(r.json()) == 21, "catalog: 21 services", r.text[:200])

    r = api.post("/auth/login", json={"phone": DEMO_PHONE, "password": DEMO_PASSWORD})
    if not check(r.status_code == 200, "demo parent can log in (run seed.py --yes first)", r.text[:200]):
        return
    api.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    r = api.get("/cases", params={"today": today})
    cases = {c["label"]: c for c in r.json().get("cases", [])} if r.status_code == 200 else {}
    alikhan, amina = cases.get("Алихан, 3 года"), cases.get("Амина, 6 лет")
    check(bool(alikhan and amina), "both seed cases listed", r.text[:200])
    if alikhan and amina:
        check(alikhan["worst_level"] == 1 and alikhan["overdue_count"] == 1, f"Алихан: one step overdue, level 1 on {today}")
        check(amina["worst_level"] == 2 and amina["overdue_count"] == 1, f"Амина: school enrolment overdue, level 2 on {today}")
        check(r.json()["load"]["norm_max"] == 30, "curator load against the 10–30 norm")

        r = api.get(f"/parent/cases/{amina['id']}", params={"today": today})
        steps = r.json().get("steps", []) if r.status_code == 200 else []
        late = [(s["step_id"], s["days_overdue"]) for s in steps if s["days_overdue"]]
        check(late == [("SPECIAL_SCHOOL_ENROLL", 12)], "parent sees the approved plan, 12 days on school", str(late))
        check(all("rationale" not in s for s in steps), "parent view has no curator rationale")

        r = api.post(f"/plans/{amina['plan_id']}/steps", json={"service_id": "NOT_IN_CATALOG"})
        check(r.status_code == 422, "adding a service outside the catalog is refused (422)", str(r.status_code))

    if args.web:
        web = args.web.rstrip("/")
        r = httpx.get(f"{web}/login", timeout=60, follow_redirects=True)
        check(r.status_code == 200, "frontend /login loads", str(r.status_code))
        r = api.options(
            "/cases", headers={"Origin": web, "Access-Control-Request-Method": "GET",
                               "Access-Control-Request-Headers": "authorization"}
        )
        allowed = r.headers.get("access-control-allow-origin")
        check(allowed == web, "CORS allows the frontend origin (CORS_ORIGINS on Railway)", f"got {allowed!r}")

    failed = [name for ok, name in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
