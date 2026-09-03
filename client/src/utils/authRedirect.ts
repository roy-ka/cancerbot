// get_current_user (src/deps/auth.py) rejects a session with 401 and a
// plain-string detail — there's no structured `code` field to check, so
// matching this exact string is the only way to tell "deletion was
// scheduled from another device" apart from a plain expired/invalid token.
const PENDING_DELETION_DETAIL = 'Account pending deletion'

/**
 * Whether a failed auth-gated fetch was specifically a pending-deletion
 * rejection. Consumes the response body (safe to call once per response).
 */
export async function isPendingDeletionResponse(res: Response): Promise<boolean> {
  if (res.status !== 401) return false
  const body = await res.json().catch(() => null)
  return body?.detail === PENDING_DELETION_DETAIL
}

/** Login path to redirect to after an auth failure, explaining why when known. */
export function loginPathForAuthFailure(pendingDeletion: boolean): string {
  return pendingDeletion ? '/login?reason=pending_deletion' : '/login'
}
