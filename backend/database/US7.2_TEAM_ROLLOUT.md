# Coordinated US7.2 schema/UTC rollout

This is an operator procedure, not an executed migration. Do not start the new
backend against a pre-004 database. Source integration and isolated verification
do not establish readiness of every teammate's database. Each operator must
complete the preflight below and obtain explicit approval for their target.
No application startup hook applies DDL or rewrites historical timestamps.

Use [the UTC readiness report](US7.2_UTC_READINESS.md) and
[the original MySQL migration checkpoint](US7.2_MIGRATION_004_VERIFICATION.md).
Fresh databases use `like_home_database_init.sql` only; never run ALTER migrations
001–004 afterward. The procedure below covers existing databases.

## 1. Identify the target and actual schema

Record the owner, host, port, database name, server version, deployed Git commit,
maintenance window and recovery owner. Teammates may use different instances and
schema names. Use explicit TCP connection options and a password prompt; do not
paste passwords or copy `.env` values into logs. Examples below are templates
for the approved operator, not commands that were run in this increment:

```bash
LH_DB_HOST='replace-with-approved-host'
LH_DB_PORT='3306'
LH_DB_USER='replace-with-approved-user'
LH_DB_NAME='replace_with_approved_schema'
LH_MYSQL=(--protocol=TCP --host="$LH_DB_HOST" --port="$LH_DB_PORT" --user="$LH_DB_USER" --password)
mysql "${LH_MYSQL[@]}" "$LH_DB_NAME"
```

In that interactive connection run read-only inspection:

```sql
SELECT DATABASE(), @@hostname, @@port, VERSION(), @@server_id;
SELECT @@global.time_zone, @@session.time_zone,
       @@global.sql_mode, @@session.sql_mode, @@tx_isolation;
SHOW CREATE TABLE users;
SHOW CREATE TABLE hotels;
SHOW CREATE TABLE room_types;
SHOW CREATE TABLE reservations;
SHOW CREATE TABLE payments;

SELECT TABLE_NAME, ENGINE
FROM information_schema.TABLES
WHERE TABLE_SCHEMA=DATABASE();

SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA=DATABASE()
  AND ((TABLE_NAME='users' AND COLUMN_NAME='session_version')
    OR (TABLE_NAME='hotels' AND COLUMN_NAME='hotel_token')
    OR (TABLE_NAME='reservations' AND COLUMN_NAME IN ('guest_full_name','guest_email','revision'))
    OR TABLE_NAME IN ('reservation_change_events','reservation_change_adjustments'))
ORDER BY TABLE_NAME, ORDINAL_POSITION;

SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA=DATABASE()
ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;
```

There is no migration-version tracking table in this repository. Infer completed
milestones from exact object definitions, then record an operator checklist:

| Milestone | Required objects |
| --- | --- |
| 001 | `users.session_version`: INT, NOT NULL, default 0. |
| 002 | Non-null unique `hotels.hotel_token`, complete `cache_hotels` and `hotel_partners` tables/FKs. Existing hotel IDs preserved. |
| 003 | Nullable `reservations.guest_full_name` and `guest_email`. |
| 004 | Unsigned, non-null `reservations.revision` default 0; `ix_reservations_user_dates`; complete event/adjustment tables, indexes and FKs from migration 004. |

Do not label a migration complete based on one column/table alone. Any partial
object set or conflicting type/index/constraint is a STOP condition requiring an
explicit recovery plan, not permission to rerun the whole file.

## 2. Check data, engine, timestamp and strict-mode prerequisites

Require InnoDB for referenced/ledger tables, compatible MySQL JSON and DATETIME(6)
support (the live checkpoint uses 5.7.44), signed INT referenced primary keys and
existing DECIMAL(10,2) monetary columns. Compare all definitions with the scripts.
Inspect known anomalies without deleting or fabricating data:

```sql
SELECT COUNT(*) FROM reservations r LEFT JOIN users u ON u.user_id=r.user_id WHERE u.user_id IS NULL;
SELECT COUNT(*) FROM reservations r LEFT JOIN room_types t ON t.room_type_id=r.room_type_id WHERE t.room_type_id IS NULL;
SELECT COUNT(*) FROM room_types t LEFT JOIN hotels h ON h.hotel_id=t.hotel_id WHERE h.hotel_id IS NULL;
SELECT COUNT(*) FROM payments p LEFT JOIN reservations r ON r.reservation_id=p.reservation_id WHERE r.reservation_id IS NULL;
SELECT reservation_id, COUNT(*) FROM payments WHERE payment_type='booking'
GROUP BY reservation_id HAVING COUNT(*) <> 1;
SELECT COUNT(*) FROM reservations WHERE check_out_date <= check_in_date;
```

Also identify reservations without a booking Payment. Preserve ambiguous legacy
payments for separate review; do not invent an adjustment/history record to make
them eligible. MySQL 5.7 parses but does not enforce the stay CHECK constraint.

Record actual timestamp column types/precision and known historical client/session
time zones. TIMESTAMP retains an instant but renders in the current session zone;
DATETIME retains literal fields. Neither reconstructs an unknown original client
clock mistake. Review representative known records in an isolated restored copy
using the old session zone and UTC. Preserve epoch values for TIMESTAMP and literal
values for DATETIME; do not automatically shift existing records.

The UTC initializer deliberately preserves SQL mode. Require a validated strict
financial-write mode such as STRICT_TRANS_TABLES or STRICT_ALL_TABLES on actual
application sessions. Additional NO_ZERO_DATE/NO_ZERO_IN_DATE flags can reject
legacy values that the previous verification mode accepted. Non-strict mode can
clip DECIMAL overflow, as demonstrated by the UTC tests. Resolve per-environment
mode/data incompatibilities separately; do not weaken mode or change global mode
to get a migration or test through.

## 3. Freeze writes and capture a baseline

Stop every backend worker, scheduler and writer for this database. Block new
checkout/payment/change/cancellation requests and confirm no teammate instance
still writes to the same target. Keep the maintenance boundary in place through
schema verification, updated-code preflight and synthetic smoke checks.

With a read-only inspection connection, `SET SESSION time_zone='+00:00'` before
baseline timestamp exports. This changes only that inspection session. Capture
SHOW CREATE TABLE, counts, booking/payment amount/status aggregates and ordered
exports of every existing column in users/hotels/room_types/reservations/payments.
Use primary-key order and a format that preserves NULLs, Unicode, dates and money.
Keep these exports with the backup. After 004, compare the same original columns,
excluding the newly added revision column. Counts or monetary sums alone do not
prove individual records survived unchanged.

## 4. Create and restore-test a backup

Use a compatible MySQL client and sufficient backup permissions. Write to a
restricted operator-owned backup directory with enough space. With writes stopped
and all data tables InnoDB, a schema-and-data example is:

```bash
umask 077
LH_BACKUP_FILE='/replace/with/operator-owned-backup/likehome-before-004.sql'
mysqldump "${LH_MYSQL[@]}" --single-transaction --quick --tz-utc --hex-blob \
  --routines --events --triggers "$LH_DB_NAME" > "$LH_BACKUP_FILE"
shasum -a 256 "$LH_BACKUP_FILE"
```

Require exit status zero, a nonempty complete dump and recorded checksum. Verify
client compatibility flags rather than assuming MySQL 8-only options work with
5.7 clients. `--tz-utc` preserves TIMESTAMP instants through dump/restore;
it does not repair historical clock errors or reinterpret DATETIME values.

Restore the dump into a new disposable instance with no access to team data and
no enabled application/jobs/event scheduler. Use the intended schema name there,
inspect schema definitions and compare the ordered baseline exports/counts.
Dry-run all missing migrations there and run the verification/smoke procedure.
A checksum alone is not restoration proof. Record the successful restore command,
instance identity, comparison results and recovery duration before live approval.

## 5. Prepare correctly targeted migration copies

The SQL files are not idempotent. 001, 002 and 004 contain `USE likehome_db;`;
003 relies on the connection's selected database. Supplying another database on
the CLI does not override a USE statement. Do not alter committed migration files.
Prepare and review operator-owned copies for the actual approved schema:

```bash
LH_MIGRATION_DIR="$(mktemp -d)"
python3 - "$LH_DB_NAME" "$LH_MIGRATION_DIR" <<'PY'
import re, sys
from pathlib import Path
schema, output = sys.argv[1:]
if not re.fullmatch(r'[A-Za-z0-9_]+', schema):
    raise SystemExit('Stop: nonstandard schema identifier requires a separately reviewed script')
source = Path('backend/database/migrations')  # Run from repository root.
for name in ('001_add_session_version.sql', '002_add_hotel_tokens_cache_and_partners.sql',
             '003_add_reservation_guest_information.sql', '004_add_reservation_change_persistence.sql'):
    sql = (source / name).read_text()
    uses = sql.count('USE likehome_db;')
    assert uses == (0 if name.startswith('003') else 1)
    sql = sql.replace('USE likehome_db;', f'USE `{schema}`;')
    if not uses:
        sql = f'USE `{schema}`;\n' + sql
    (Path(output) / name).write_text(sql)
PY
```

Review the target, diff and checksum of every generated copy. For each numbered
migration, apply only if its complete milestone is absent and its prerequisites
are satisfied. Stop on partial state. Preserve legacy hotel IDs and 002's internal
`legacy:<id>` tokens; these are not real SerpApi property tokens. Do not rerun a
completed migration or apply existing-database ALTER files to fresh initialization.

## 6. Apply applicable 001 → 002 → 003 → 004 individually

After explicit approval, and with writers still stopped, execute one reviewed
copy at a time. This example is only for a target confirmed to need 004:

```bash
mysql "${LH_MYSQL[@]}" "$LH_DB_NAME" < "$LH_MIGRATION_DIR/004_add_reservation_change_persistence.sql"
```

For missing earlier milestones use their respective copies in order, verify each
before proceeding and retain exit status/output without credentials. Do not use
`--force`, ignore errors or wrap the batch in a transaction expecting rollback.
MySQL DDL can commit prior work and cannot be undone by ROLLBACK.

## 7. Verify schema and preserved records

Repeat the baseline inspection/ordered exports under a UTC inspection session.
Verify original rows/IDs, guest fields, dates, statuses, totals, payments and
timestamps exactly match the pre-migration baseline. 004 alone should add revision
0 for existing reservations, with both new history tables empty. Earlier applicable
migrations have only their documented additions/token backfill. Do not deploy if
any unexplained record change occurs.

Run SHOW CREATE TABLE for both new tables. Compare all types, indexes, unique
constraints and FKs with 004, including quote JTI uniqueness, reservation/revision
uniqueness, adjustment role uniqueness and same-change reconciliation parent FK:

```sql
SELECT COUNT(*), MIN(revision), MAX(revision) FROM reservations;
SELECT COUNT(*) FROM reservation_change_events;
SELECT COUNT(*) FROM reservation_change_adjustments;
SHOW CREATE TABLE reservation_change_events;
SHOW CREATE TABLE reservation_change_adjustments;
SELECT TABLE_NAME, CONSTRAINT_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME,
       REFERENCED_COLUMN_NAME, ORDINAL_POSITION
FROM information_schema.KEY_COLUMN_USAGE
WHERE CONSTRAINT_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION;
SELECT TABLE_NAME, CONSTRAINT_NAME, DELETE_RULE, UPDATE_RULE
FROM information_schema.REFERENTIAL_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA=DATABASE();
```

## 8. Verify actual application UTC sessions

Deploy the tested UTC engine/default code only after the schema check succeeds.
Restart workers so old pool connections and host-local defaults cannot survive.
From the approved application environment, verify its engine, not only a mysql CLI
session. This read-only example must not be run here against development:

```python
from sqlalchemy import text
from app.config.database import engine

for _ in range(2):
    with engine.connect() as connection:
        print(connection.execute(text(
            "SELECT CONNECTION_ID(), @@session.time_zone, @@global.time_zone, "
            "@@session.sql_mode, UTC_TIMESTAMP(6), NOW(6)"
        )).one())
engine.dispose()  # This dedicated preflight process owns its pool; workers stay stopped.
with engine.connect() as connection:
    assert connection.execute(text("SELECT @@session.time_zone")).scalar_one() == '+00:00'
```

Require UTC on new/reused/reconnected sessions and validated strict mode. Global
zone need not be UTC and must not be changed by this initializer. Verify host clock
synchronization; session UTC does not fix a wrong clock. Review known legacy
TIMESTAMP display differences and unknown historical DATETIME/client conventions
before relying on those timestamps in any future business comparison.

## 9. Smoke-check and resume writes deliberately

First run `backend/.venv/bin/python -m pytest -q -p no:cacheprovider backend/tests`
under the documented offline isolation settings (dotenv disabled, synthetic
unusable DB/provider configuration, no network). Run the opt-in disposable MySQL
verifier separately for schema/UTC/locking evidence. Neither command should use
real team data or real SerpApi. Restore-copy service smoke tests must cover auth,
search with mocks, booking creation/payment/cancellation, quote expiry, confirmation
retry, charge settlement/retry and read-only financial summary.

On the actual target, keep initial smoke checks read-only: existing customer
authentication, owned booking/payment reads, route/OpenAPI registration, missing
resource 404s and migrated-schema UTC reads. Never mutate real bookings just to
smoke-test the rollout. Mutating tests require separately approved synthetic
records and mocked providers in staging/disposable environments. Invalidate any
pre-rollout change quotes by requiring a fresh review after maintenance; do not
attempt to reinterpret their historical fingerprints. Resume team writers only
after the migration owner accepts all results and the rollback boundary below.

## 10. Failure and recovery

Keep writers stopped on any failed DDL, data comparison, strict-mode, UTC or smoke
check. Record exact failing statement/object state. Inspect partial schema before
planning the next action; do not rerun the full file or drop history to make an
error disappear. Prefer a reviewed roll-forward repair on the restore-tested copy.

Before any post-cutover writes, recovery may restore the verified pre-migration
backup to a new approved instance and use its compatible previous application
release, following the owner's recovery plan. Do not overwrite the failed instance
without preserving its forensic/schema state.

After payments or changes resume, a pre-migration backup omits new financial
history. Restoring it blindly loses transactions. Freeze writes again, preserve
complete current data/binlogs and coordinate recovery/reconciliation; do not
silently downgrade to code that ignores revision or ledger updates. Event receipts,
paid charges, credits and cancellation reconciliation are history, not disposable
cache. Do not drop ledger tables, truncate them, delete history or remove revision
as a generic rollback. Restrictive FKs intentionally protect those relationships.

## References

MySQL documents [session time-zone behavior](https://docs.oracle.com/cd/E17952_01/mysql-5.7-en/time-zone-support.html),
[TIMESTAMP and DATETIME](https://docs.oracle.com/cd/E17952_01/mysql-5.7-en/datetime.html),
[implicit DDL commits](https://docs.oracle.com/cd/E17952_01/mysql-5.7-en/implicit-commit.html),
and [mysqldump backup options](https://docs.oracle.com/cd/E17952_01/mysql-5.7-en/mysqldump.html).
Repository-specific results come from the linked verification reports.
