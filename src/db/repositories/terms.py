from src.db.models import TermsAndConditions, User


def get_latest_terms(db) -> TermsAndConditions | None:
    return (
        db.query(TermsAndConditions)
        .order_by(TermsAndConditions.version.desc())
        .first()
    )


def accept_terms(db, user_id, version: int) -> None:
    db.query(User).filter(User.id == user_id).update({"terms_version": version})
    db.commit()
