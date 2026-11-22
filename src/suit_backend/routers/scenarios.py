from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from suit_backend.deps import CurrentUser, DBSession
from suit_backend.models import Phrase, Scenario
from suit_backend.schemas import PhraseResponse, ScenarioResponse

router = APIRouter(tags=["scenarios"])


@router.get("/scenarios", response_model=list[ScenarioResponse])
def list_scenarios(_: CurrentUser, db: DBSession) -> list[Scenario]:
    query = select(Scenario).where(Scenario.is_active.is_(True)).order_by(Scenario.id)
    return list(db.scalars(query))


@router.get("/phrases", response_model=list[PhraseResponse])
def list_phrases(
    current_user: CurrentUser,
    db: DBSession,
    scenario_id: str = Query(min_length=1, max_length=40),
) -> list[Phrase]:
    return list(
        db.scalars(
            select(Phrase)
            .where(
                Phrase.scenario_id == scenario_id,
                Phrase.is_active.is_(True),
                or_(
                    Phrase.organization_id.is_(None),
                    Phrase.organization_id == current_user.organization_id,
                ),
            )
            .order_by(Phrase.organization_id.is_(None).desc(), Phrase.category, Phrase.text)
        )
    )

