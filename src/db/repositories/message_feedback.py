from src.db.models import MessageFeedback

VOTE_UP = 1
VOTE_DOWN = -1


def set_feedback(db, message_id, user_id, vote: int) -> int | None:
  """Upsert the user's vote on a message. Submitting the same vote again
  toggles it off (returns None) rather than being a no-op — the natural
  "click thumbs-up twice to unvote" interaction. Returns the resulting vote
  (1, -1, or None if cleared)."""
  existing = (
    db.query(MessageFeedback)
    .filter(MessageFeedback.message_id == message_id, MessageFeedback.user_id == user_id)
    .first()
  )
  if existing is None:
    db.add(MessageFeedback(message_id=message_id, user_id=user_id, vote=vote))
    db.commit()
    return vote

  if existing.vote == vote:
    db.delete(existing)
    db.commit()
    return None

  existing.vote = vote
  db.commit()
  return vote


def get_feedback_for_messages(db, message_ids, user_id) -> dict:
  """Bulk lookup of the given user's vote per message, for attaching
  feedback state when listing a page of messages. Returns
  {str(message_id): vote}, omitting messages with no vote from this user."""
  if not message_ids:
    return {}
  rows = (
    db.query(MessageFeedback)
    .filter(MessageFeedback.message_id.in_(message_ids), MessageFeedback.user_id == user_id)
    .all()
  )
  return {str(row.message_id): row.vote for row in rows}
