from datetime import datetime, timezone

from src.db.models import UserProfile

AGE_BANDS = ["under_18", "18_39", "40_64", "65_plus"]
TREATMENT_STATUSES = [
  "newly_diagnosed",
  "in_active_treatment",
  "post_treatment_surveillance",
  "recurrence_or_progression",
  "chronic",
]

_FIELDS = ["cancer_type", "stage", "biomarkers", "age_band", "treatment_status"]

_AGE_BAND_LABELS = {
  "under_18": "under 18",
  "18_39": "18-39",
  "40_64": "40-64",
  "65_plus": "65+",
}
_TREATMENT_STATUS_LABELS = {
  "newly_diagnosed": "newly diagnosed",
  "in_active_treatment": "in active treatment",
  "post_treatment_surveillance": "post-treatment surveillance",
  "recurrence_or_progression": "recurrence or progression",
  "chronic": "managed as a chronic condition",
}


def get_profile(db, user_id) -> UserProfile | None:
  return db.query(UserProfile).filter(UserProfile.user_id == user_id).first()


def upsert_profile(db, user_id, **fields) -> UserProfile:
  """Create or update the user's profile row. Fields not passed are left
  unchanged on an existing row; omitted entirely (None-defaulted) on a new
  one. Called with no fields at all for a "Skip" — that still creates the
  row, which is what stops the onboarding offer from resurfacing."""
  profile = get_profile(db, user_id)
  if profile is None:
    profile = UserProfile(user_id=user_id, **{f: fields.get(f) for f in _FIELDS})
    db.add(profile)
  else:
    for f in _FIELDS:
      if f in fields:
        setattr(profile, f, fields[f])
    profile.updated_at = datetime.now(timezone.utc)
  db.commit()
  db.refresh(profile)
  return profile


def delete_profile(db, user_id) -> bool:
  profile = get_profile(db, user_id)
  if profile is None:
    return False
  db.delete(profile)
  db.commit()
  return True


def render_profile_context(profile: UserProfile | None) -> str | None:
  """Human-readable rendering of the populated fields, for the prompt
  preamble — see OllamaConnector._build_prompt's PATIENT CONTEXT block.
  Returns None if there's nothing to render (no profile, or all fields
  empty), so callers can skip the block entirely rather than emit an
  empty one."""
  if profile is None:
    return None
  lines = []
  if profile.cancer_type:
    lines.append(f"Cancer type: {profile.cancer_type}")
  if profile.stage:
    lines.append(f"Stage: {profile.stage}")
  if profile.biomarkers:
    lines.append(f"Biomarkers/mutations: {profile.biomarkers}")
  if profile.age_band:
    lines.append(f"Age band: {_AGE_BAND_LABELS.get(profile.age_band, profile.age_band)}")
  if profile.treatment_status:
    lines.append(f"Treatment status: {_TREATMENT_STATUS_LABELS.get(profile.treatment_status, profile.treatment_status)}")
  return "\n".join(lines) if lines else None


def has_populated_profile(db, user_id) -> bool:
  """Whether the user has a profile row with at least one field actually
  filled in — used to decide whether the per-conversation toggle and the
  prompt preamble have anything to work with."""
  profile = get_profile(db, user_id)
  if profile is None:
    return False
  return any(getattr(profile, f) for f in _FIELDS)
