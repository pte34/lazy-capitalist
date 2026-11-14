-- Additive indexes for runtime foreign keys and orphan-claim scans.
BEGIN;
CREATE INDEX runtime_budget_order_idx ON lc_runtime.order_budget(order_id);
CREATE INDEX runtime_audit_job_idx ON lc_runtime.audit_events(job_id);
CREATE INDEX runtime_delivery_lease_idx ON lc_runtime.report_deliveries(updated) WHERE status='running';
INSERT INTO lc_runtime.schema_migrations(version) VALUES('runtime_indexes_v3');
COMMIT;
