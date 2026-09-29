/**
 * Authentication contract.
 *
 * TypeScript mirror of `src/harsh_quant_os/contracts/auth.py`; the Python
 * models are authoritative. Field names and the shared fixture are compared
 * in both directions:
 *
 * - `tests/unit/auth-contract.test.ts` (this side of the comparison)
 * - `tests/api/test_auth_contract_parity.py` (the Python side)
 *
 * Both read `tests/contracts/auth-context.json`, so a payload accepted by one
 * language must be accepted by the other.
 *
 * Note what is absent: no token field and no session id. The session token
 * lives only in an `HttpOnly` cookie, so no JSON payload can expose it to
 * JavaScript.
 */

/** The authenticated account, as login and `/me` report it. */
export interface UserProfile {
  id: string;
  email: string;
  display_name: string | null;
  is_superuser: boolean;
  created_at: string;
}

/** Lifetime of the session that authorised the current request. */
export interface SessionProfile {
  issued_at: string;
  expires_at: string;
}

/** Answer to "who am I, and how long may I stay?". */
export interface AuthContextResponse {
  user: UserProfile;
  session: SessionProfile;
}

/** Credentials posted to `POST /api/v1/auth/login`. */
export interface LoginRequest {
  email: string;
  password: string;
}
