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

PROFILE_FIELDS = ["cancer_type", "stage", "biomarkers", "age_band", "treatment_status"]

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
_FIELD_LABELS = {
  "cancer_type": "cancer type",
  "stage": "stage",
  "biomarkers": "biomarkers/mutations",
  "age_band": "age band",
  "treatment_status": "treatment status",
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
    profile = UserProfile(user_id=user_id, **{f: fields.get(f) for f in PROFILE_FIELDS})
    db.add(profile)
  else:
    for f in PROFILE_FIELDS:
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
  return any(getattr(profile, f) for f in PROFILE_FIELDS)


def _display_value(field: str, value: str) -> str:
  if field == "age_band":
    return _AGE_BAND_LABELS.get(value, value)
  if field == "treatment_status":
    return _TREATMENT_STATUS_LABELS.get(value, value)
  return value


def render_profile_recall(profile: UserProfile | None, fields: list[str], has_untracked_ask: bool = False) -> str:
  """Deterministic (non-LLM) recall of specific saved profile fields, for a
  personal question like "what's my cancer type?" or "what stage am I?".

  Kept entirely separate from the LLM-generated literature answer — see
  OllamaConnector.classify_personal_question — so a factual, verbatim
  recite-back of what the user already told CancerBot can never be blended
  with (or mistaken for) a generated medical claim. A requested field that
  hasn't actually been saved gets an honest "not saved" line rather than
  silently omitting it or guessing; `has_untracked_ask` covers a question
  about something CancerBot doesn't track at all (e.g. treatment-line
  count, diagnosis date) with the same honest-gap framing.
  """
  lines = []
  for f in fields:
    if f not in PROFILE_FIELDS:
      continue
    label = _FIELD_LABELS.get(f, f)
    value = getattr(profile, f, None) if profile else None
    if value:
      lines.append(f"Your saved {label}: {_display_value(f, value)}")
    else:
      lines.append(f"You haven't saved your {label} yet — you can add it from the account menu.")
  if has_untracked_ask:
    lines.append(
      "CancerBot doesn't track that specific detail in your profile — only cancer type, "
      "stage, biomarkers, age band, and treatment status. You can check your own records "
      "or care team for anything more specific."
    )
  return "\n".join(lines)
