from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Phrase, Scenario

SCENARIOS = [
    ("hospital", "병원 접수·진료 안내", "접수, 예약 확인, 기초 문진, 대기 안내"),
    ("public", "공공기관 민원·복지 안내", "서류 발급, 민원 신청, 담당 창구 안내"),
    ("school", "학교 상담 · 확장 예정", "교육기관 상담 및 수업 지원"),
    ("office", "복지기관 상담 · 확장 예정", "복지 상담과 지원 신청"),
]

PHRASES = [
    ("hospital", "접수", "접수하러 왔어요.", "I would like to check in."),
    ("hospital", "예약", "예약하고 왔어요.", "I have an appointment."),
    ("hospital", "증상", "머리가 아파요.", "I have a headache."),
    ("hospital", "안내", "어디에서 기다리면 되나요?", "Where should I wait?"),
    ("hospital", "안내", "수어 통역이 필요해요.", "I need a sign language interpreter."),
    ("public", "서류", "등본을 발급받고 싶어요.", "I would like a resident record copy."),
    ("public", "신청", "전입신고를 하려고 해요.", "I would like to report a move."),
    ("public", "안내", "어느 창구로 가면 되나요?", "Which counter should I go to?"),
    ("public", "서류", "어떤 서류가 필요한가요?", "What documents do I need?"),
]


def seed_reference_data(db: Session) -> None:
    for scenario_id, title, description in SCENARIOS:
        if db.get(Scenario, scenario_id) is None:
            db.add(Scenario(id=scenario_id, title=title, description=description))
    db.flush()
    existing = db.scalar(select(Phrase.id).where(Phrase.organization_id.is_(None)).limit(1))
    if existing is None:
        for scenario_id, category, text, english in PHRASES:
            db.add(
                Phrase(
                    organization_id=None,
                    scenario_id=scenario_id,
                    category=category,
                    text=text,
                    english=english,
                )
            )
    db.commit()
