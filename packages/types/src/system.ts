/**
 * System status contract.
 *
 * TypeScript mirror of `src/harsh_quant_os/contracts/system.py`; the Python
 * models are authoritative. Field names, enum members and the shared fixture
 * are compared in both directions:
 *
 * - `tests/unit/health-contract.test.ts` (this side of the comparison)
 * - `tests/api/test_contract_parity.py` (the Python side)
 *
 * Both read `tests/contracts/system-status.json`, so a payload accepted by one
 * language must be accepted by the other.
 */

/** Liveness payload: the API process is up and identifies itself. */
export interface HealthResponse {
  status: HealthStatus;
  service: string;
  version: string;
  environment: ApiEnvironment;
}

/** Readiness payload: aggregate state plus every individual check. */
export interface ReadyResponse {
  status: ReadinessStatus;
  service: string;
  version: string;
  environment: ApiEnvironment;
  checks: ReadinessCheck[];
}

/** One named dependency and why it is or is not available. */
export interface ReadinessCheck {
  name: string;
  status: CheckStatus;
  detail: string;
}

/** `/health` answers only that the process is serving requests. */
export type HealthStatus = 'ok';

/** Aggregate readiness of the service. */
export type ReadinessStatus = 'ready' | 'not_ready';

/**
 * State of one readiness dependency. `not_configured` is deliberately distinct
 * from `ok`: in Phase 1 the database does not exist, and saying so is more
 * useful than reporting a pass that was never earned.
 */
export type CheckStatus = 'ok' | 'not_configured' | 'failed';

/** Deployment environment the process was configured with. */
export type ApiEnvironment = 'development' | 'test' | 'staging' | 'production';

export const HEALTH_STATUSES: readonly HealthStatus[] = ['ok'];

export const READINESS_STATUSES: readonly ReadinessStatus[] = ['ready', 'not_ready'];

export const CHECK_STATUSES: readonly CheckStatus[] = ['ok', 'not_configured', 'failed'];

export const API_ENVIRONMENTS: readonly ApiEnvironment[] = [
  'development',
  'test',
  'staging',
  'production',
];
