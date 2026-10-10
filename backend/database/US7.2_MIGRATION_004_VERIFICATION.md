# US7.2 Migration 004 verification — 2026-10-10

**Isolated database-readiness gate: READY.** MySQL 5.7.44 verification passed:
**43 live tests**, plus the unchanged **734-test backend regression suite**.
Development MySQL was never contacted or migrated. No endpoints were activated.
Actual endpoint deployment remains conditional on a separately authorized target
migration and appropriate UTC/strict-mode connection configuration.

The 2026-10-09 attempt was blocked by a missing Docker socket. On resumption,
the socket existed but the execution sandbox denied access. Approved execution
access resolved that restriction; it does not mean ordinary sandbox commands
can access Docker. Docker Desktop was independently inspected before provisioning.

## A–R result report

| Item | Actual result |
| --- | --- |
| A. Starting Git state | `feature/reservation-change`, HEAD `1aa65db8ce5f6886c94da260b5879fe37b2b248d`. The two documentation changes from the earlier blocked attempt were already present and were updated for this resumption. The separate frontend worktree was untouched. No branch switch, commit, push, merge or rebase. |
| B. Disposable environment/isolation | Docker context pinned to `desktop-linux`, local Unix socket required. Uniquely labeled amd64 container, tmpfs-only database data, no bind mounts/reused volumes, synthetic credentials, random loopback-only port. Inspected port/mount/image/label identity and checked a random server marker before DDL. Process audit hook permits only the verified disposable host/port; dotenv is disabled. |
| C. MySQL version | MySQL **5.7.44**, InnoDB, REPEATABLE-READ, `STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION`, UTC test sessions. Docker Engine **29.2.1** on arm64. Manifest supplies only a linux/amd64 runtime image; explicit `--platform linux/amd64` emulation worked. |
| D. Migration 004 | Successfully applied once per newly provisioned upgraded schema; never applied to a fresh-install schema. No SQL correction was needed. Each of the three verification invocations used a new disposable environment; all were removed. |
| E. Existing-data preservation | Exact before/after snapshots match for 2 users, 1 hotel, 2 room types, 2 reservations and 2 booking Payments (pending/paid). Original IDs, names, amounts, statuses, dates, guest information and timestamps are unchanged; both existing revisions became zero. New history tables were empty immediately after migration. |
| F. Tables/indexes/FKs | Revision/default/user-date index, new columns/nullability, exact money precision, JSON, microseconds, JTI charset/collation, InnoDB, quote/revision uniqueness, role/parent uniqueness and all FKs verified live. Duplicate/orphan/cross-change inserts and restrictive deletes rejected by MySQL on both schema paths. |
| G. Fresh versus upgrade | All tables' column types, nullability, defaults, charset/collation, engines, index definitions and FK targets/actions match. Only reservation column ordinal positions differ: upgraded revision is column 11, fresh revision is column 4, shifting intervening columns. No difference was silently hidden. |
| H. SQLAlchemy | Current registered models load both historical booking-payment states and revision-zero reservations; persist/reload events, primary adjustments and linked reconciliations; query owner/payment/event relationships; reject cross-change parents. Existing ORM/DDL differences were preserved and are detailed below. |
| I. Decimal precision | Ledger Numeric fields return exact Decimal values for 0.01, 0.10, 226.82 and 99999999.99. Legacy reservation/payment Float mappings round-trip those values without cent corruption after the existing canonical-money conversion. JSON money remains fixed decimal strings. |
| J. InnoDB concurrency | Observed actual INNODB_LOCK_WAITS for User, Reservation, Payment and Adjustment rows; commit and rollback release every tested lock. Duplicate quote race rejects the losing insert and rolls back its candidate reservation write. Real service races pass for identical quotes, competing revisions, same-user overlapping stays, and settlement versus cancellation. RR snapshot replacement and rollback of flushed reservation/room/event/adjustment writes pass. No unexpected deadlock or stale-snapshot defect appeared in these bounded cases. |
| K. Financial ledger | Real confirmation → charge settlement → second change/credit → cancellation sequence preserves both event receipts and both primary history records. Original booking amount remains 226.80; cancellation applies the existing refunded marker. Linked equal/opposite 45.36 credit and 68.04 debit coexist, uniqueness/FKs hold, and cancellation fee is 37.80. No external financial transaction. |
| L. Files changed | `backend/database/README.md`, `backend/database/US7.2_MIGRATION_004_VERIFICATION.md`, `backend/database/verification/run_mysql57_verification.py`, `backend/database/verification/test_mysql57_contract.py`. No production SQL, models, services, routes, frontend or environment-file changes. |
| M. Focused results | Final live run: **43 passed in 3.12s**, no warnings. Direct invocation without the disposable runner: **43 skipped in 0.54s**, verifying that ordinary test collection cannot opt into an application database. |
| N. Full regression | **734 passed in 15.51s**, preserving the baseline. Two existing Starlette/httpx and anyio BlockingPortal deprecation warnings. `git diff --check` passes, including whitespace checks on new files. |
| O. Cleanup | All three labeled disposable containers removed and tmpfs discarded. Original stopped container IDs/states and volume IDs preserved. The MySQL image downloaded for this task was removed after testing; no unrelated image was removed. |
| P. Development safety | Development MySQL untouched; no existing DB container/volume used. No real booking/account data, credentials or provider calls. `.env` files unchanged. Normal regression fixtures retain SQLite/mocked providers. |
| Q. Blockers/defects | Docker is sandbox-restricted and requires approved execution access here. No remaining migration or persistence blocker was demonstrated. Known legacy mappings, UTC session prerequisites and limits of finite concurrency smoke tests remain documented. |
| R. Endpoint readiness | **READY for this isolated database-readiness gate.** Actual development deployment still requires the separately authorized migration and connection preflight. Endpoints remain unregistered; activation/frontend integration are outside this task. |

## Actual environment and commands

The final test container was `likehome-us72-92d0ed3017b14a2a8d507698c2b946e2`,
container ID `e1662f4ede26d138ab390af0f2796440d12a4d4a23bc90374e9303205c759e9e`.
Its only published port was `127.0.0.1:57160 → 3306`; it had no host-data mounts
and no persistent volumes. The two isolated schemas were
`us72_upgrade_92d0ed3017b1` and `us72_fresh_92d0ed3017b1`. These resources no longer
exist. The host `mysql` client and application `SessionLocal` were never used.

Architecture checks and image acquisition:

```bash
docker context show
docker version --format '{{json .Server}}'
docker ps -a --format '{{.ID}} {{.Names}} {{.Image}} {{.Ports}}'
docker volume ls --format '{{.Name}}'
docker buildx imagetools inspect mysql:5.7.44
docker pull --platform linux/amd64 mysql:5.7.44
```

The manifest digest was
`sha256:4bc6bc963e6d8443453676cae56536f4b8156d78bae03c0145cbe47c2aad73bb`;
the runtime manifest was linux/amd64. No arm64 runtime manifest was available.
The runner pins Docker's local context and accepts no user-supplied DB URL,
credential file or existing container/volume argument. It establishes connection
settings before startup, verifies the owned resource before connecting, and checks
MySQL version/server marker on every newly opened connection.

From the repository root, the exact final verification command was:

```bash
backend/.venv/bin/python backend/database/verification/run_mysql57_verification.py \
  --disposable --evidence /private/tmp/likehome-us72-mysql57-evidence.json
```

This file contains the sanitized before/after synthetic snapshots, full compared
schema metadata, column order, observed SQL waits and financial summary. It has
no credentials or raw signed quotes. The harness writes evidence after removing
its container. Future runs create new names/credentials/markers and a new port;
do not reuse the retired port or schema names above.

Normal collection safety was checked with:

```bash
env PYTHON_DOTENV_DISABLED=1 backend/.venv/bin/python -m pytest \
  -q -p no:cacheprovider backend/database/verification/test_mysql57_contract.py
```

All 43 tests skip unless the Docker-owning runner supplies its in-process context.
The runner uses the existing virtual environment, pytest, PyMySQL and SQLAlchemy;
no new dependencies or testing framework were installed. Python: 3.14.3.

## Migration ordering and preservation evidence

The pre-004 schema comes directly from repository history:

```bash
git show 57088923e952e9c4baba48cc71d2a9f94e4a138e:backend/database/like_home_database_init.sql
```

It already includes session_version, hotel tokens/cache/partners and guest fields,
so migrations 001–003 are prerequisites already satisfied by that historical SQL.
No prerequisite was invented, reapplied or reverse-engineered by dropping current
columns. The harness changes only the CREATE DATABASE/USE target in in-memory
copies, validates the test-name pattern, and executes repository SQL via PyMySQL:

1. Historical initializer into the disposable upgrade schema; synthetic seeding.
2. Complete historical snapshots before and after
   `004_add_reservation_change_persistence.sql`, executed once.
3. Current `like_home_database_init.sql` into a distinct fresh schema, without 004.
4. Equivalent synthetic seeds for actual insert/delete enforcement tests on fresh.

The initial IDs were users 7001/7002, hotel 7101, rooms 7201/7202,
reservations 7301/7302 and Payments 7401/7402. Reservation totals were 210.02;
booking amounts were 226.82, with pending/paid states respectively. Dates,
nullable/historical guest fields and fixed UTC creation timestamps matched exactly.
All later tests used additional synthetic records in those same disposable schemas.

The metadata comparison uses relative table/column/FK identities because schema
names intentionally differ. It does not normalize financial types, defaults,
nullability, index definitions or FK actions. It separately records the full
reservation column order rather than concealing its difference.

## Constraints and ORM findings

- Revision: unsigned INT, NOT NULL, default zero; user/date index order verified.
- Events: unique JTI and `(reservation_id, revision_after)`; five restrictive
  deletion FKs with UPDATE CASCADE; expected owner/payment/room indexes.
- Adjustments: unique `(change_id, entry_role)`, unique nullable parent and
  unique `(adjustment_id, change_id)`; event FK and composite parent/change FK
  with RESTRICT actions. MySQL rejects unrelated change parents with error 1452,
  duplicate keys with 1062 and restrictive deletes with 1451.
- Both new tables and existing money tables use InnoDB. Money is DECIMAL(10,2),
  JSON extraction works and malformed JSON is rejected (3140), DATETIME(6)
  microseconds survive ORM round trips, and JTI uses ascii/ascii_bin.
- MySQL 5.7 does **not** enforce legacy date CHECK clauses or ledger business
  policies. Deliberately invalid dates/negative adjustment amounts were accepted
  inside transactions and rolled back. Positive amounts, owner/payment membership,
  parent role, opposite kind/equal amount and immutable receipts remain application
  responsibilities. Passing FK tests does not replace those service guards.

Existing ORM differences are unchanged: Reservation.total_price, Payment.amount
and RoomType.price_per_night are Float over SQL DECIMAL; legacy models do not all
map their SQL FKs, and legacy created_at mappings use DateTime/client defaults
where SQL uses TIMESTAMP/server defaults. New ledger money is Numeric/Decimal.
No model definition was changed to conceal a mismatch, and `create_all()` was
never used to migrate or install MySQL. The representative legacy cent checks pass,
but this is not a coordinated conversion of the older mappings to Decimal.

All live test connections explicitly initialize UTC. Migration SET time_zone is
session-local, so application-wide UTC setup still needs deployment consideration;
this test does not certify the uncontacted development server's session defaults.

## Locking and financial scope

Eight row-lock cases were observed in `information_schema.INNODB_LOCK_WAITS`:
each of users, reservations, payments and adjustments under both commit and
rollback. Bounded worker waits verify blocking and subsequent lock acquisition,
with expected committed or rolled-back values. Independent observer connections
inspect state. A duplicate-quote transaction waits on the unique index, is rejected
on commit of the first transaction, and rolls back its own reservation mutation.

Application tests use real DAO FOR UPDATE statements and separate MySQL Sessions;
barriers coordinate attempts without replacing locks with mutexes. Four cases
cover pending/paid bookings with identical quotes or competing revisions. A
same-user race over different stays allows only one overlapping change to commit.
Another case validates settlement versus cancellation under real locks. Provider
responses are mocked, and the process network allowlist also blocks any accidental
real provider call. An injected failure after actual SQL flush proves rollback
removes reservation/room/event/adjustment candidate changes together.

The two-change ledger scenario uses the existing confirmation, settlement,
financial-summary and cancellation services: an original 226.80 booking Payment,
45.36 additional paid charge, later 68.04 recorded credit, linked cancellation
credit/debit reversals, and a separate 37.80 cancellation Payment. Receipt and
primary-entry snapshots remain identical across cancellation, including amounts
and timestamps. The approved refunded marker changes the original booking status
without changing its amount. This records internal entries, not a bank transaction.

No unexpected deadlock or stale snapshot appeared in these cases. This is a small
SQL/service smoke suite, not proof of every production interleaving, timeout,
crash-recovery, deployment or replication scenario.

## Full backend regression command

Run from `backend/`; this leaves the ordinary isolated fixture configuration in
place. Process-only synthetic placeholders override dotenv without editing files.
The audit hook forbids all socket connections and DNS lookup in this invocation.

```bash
env PYTHON_DOTENV_DISABLED=1 \
  DB_HOST=127.0.0.1 DB_PORT=1 DB_NAME=us72_offline_tests \
  DB_USER=us72_synthetic DB_PASSWORD=synthetic-test-only \
  API_KEY=synthetic-test-only EXTERNAL_API_URL=http://127.0.0.1:1 \
  JWT_SECRET_KEY=us72-isolated-test-key-32-characters \
  .venv/bin/python - <<'PY'
import sys
import pytest

def forbid_network(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise AssertionError('External network access forbidden during isolated regression tests')

sys.addaudithook(forbid_network)
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', 'tests']))
PY
```

## Later development application procedure

This task does **not** authorize or perform development application. For a later
approved maintenance window, follow [the database README](README.md#before-application-manual-only):
back up schema and data and test restoration, stop booking writes, verify target
identity/version/strict mode/InnoDB/signed INT FK prerequisites and orphan/payment
anomalies, inspect which 001–003 prerequisites are actually missing, and check for
partially created 004 objects. Apply only missing prerequisites in order, then 004
exactly once to the explicitly verified target. DDL implicitly commits; ordinary
transaction rollback cannot undo a partially applied migration.

Compare original IDs, counts, dates, amounts and statuses against the backup;
verify revision zero, empty history, and the live constraints/JSON/money behavior.
Fresh installs use only the initializer. Apply the schema before deploying the
revision-selecting ORM. Confirm application sessions use UTC and suitable strict
SQL mode. Preserve consumed-quote receipts and financial history during recovery;
never erase ledger obligations or reset revisions as an operational rollback.
Endpoint registration/frontend integration remain separate work.
