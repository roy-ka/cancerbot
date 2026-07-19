// Account deletion is no longer instant — it requires an emailed confirmation link
// plus a 7-day grace period before the background sweep removes the row (see
// src/routers/auth.py request-delete/confirm-delete and src/jobs/account_deletion.py).
// There is nothing left for teardown to do: the shared E2E_EMAIL user is meant to
// persist and be reused across runs, which is why globalSetup already tolerates a
// 400 "already registered" response when registering it.
export default async function globalTeardown() {}
