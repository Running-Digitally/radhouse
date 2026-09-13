-- Task snapshots now retain selected files, previous-result context, control
-- receipts and pending permission requests. Existing rows use additive defaults.
-- No table rewrite or extra runtime privilege is needed. The owner initializer
-- records version 2 and the ordered migration digest in radhouse_metadata so a
-- version-1 controller refuses this database before reading or changing tasks.
SELECT 1;
