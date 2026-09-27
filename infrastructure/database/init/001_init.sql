-- HARSH QUANT OS - initial database objects (executed on first container start)
--
-- Phase 0: this file exists so the development container has an explicit,
-- reviewable starting point. Migrations arrive with Phase 2 (Alembic) and
-- will take over from here.

CREATE SCHEMA IF NOT EXISTS public;

COMMENT ON SCHEMA public IS
  'HARSH QUANT OS development schema. Phase 0: no tables yet.';
