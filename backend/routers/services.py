from fastapi import APIRouter

from schemas import ServiceOut
from services.catalog import RULES, SERVICES

router = APIRouter(prefix="/services", tags=["services"])


@router.get("", response_model=list[ServiceOut])
def list_services() -> list[ServiceOut]:
    """The catalog, for the curator's «add step» dropdown."""
    return [
        ServiceOut(
            service_id=code,
            title=s["title_ru"],
            sector=s["domain"],
            responsible=s["provider_org"],
            mode=RULES[code]["mode"],
            sla_days=s.get("sla_days"),
            sla_unit=s.get("sla_unit"),
            priority_default=s["priority_default"],
            depends_on=s["depends_on"],
            ui_note=s.get("ui_note"),
        )
        for code, s in SERVICES.items()
    ]
