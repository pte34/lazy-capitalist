-- SQLite INTEGER is signed 64-bit: retain that range in references and counters.
BEGIN;
ALTER TABLE lc_runtime.report_alerts ALTER COLUMN event_id TYPE BIGINT;
ALTER TABLE lc_runtime.platform_events ALTER COLUMN audit_id TYPE BIGINT;
ALTER TABLE lc_runtime.ai_usage ALTER COLUMN input_tokens TYPE BIGINT;
ALTER TABLE lc_runtime.ai_usage ALTER COLUMN output_tokens TYPE BIGINT;
INSERT INTO lc_runtime.schema_migrations(version) VALUES('runtime_wide_counters_v4');
COMMIT;
