# US7.2 UTC database readiness — 2026-10-10

The isolated UTC configuration gate is **READY**. Executing coordinated Migration
004 rollout is **NOT READY** until each real target completes the documented
preflight, restore-tested backup, timestamp/strict-mode review and explicit rollout
approval. No existing database was contacted, migrated or rewritten. No updated
application server was started, branch committed/pushed or main merged.

## A. Initial Git state

Clean `feature/reservation-change` at
`cb9c676f8cc63c0b172a3aa2269d71094dc8172e`, matching its remote-tracking branch.
This includes the latest incorporated main checkpoint `db6dca0` and the API
checkpoint `dcc2885`. The separate frontend worktree and local main were preserved.
The starting backend baseline was 869 passing tests.

## B. Existing database configuration findings

- Application configuration built `create_engine(Config.DB_URL)` without session
  UTC initialization. `get_db` only yielded/closed a Session; it applied no DDL.
- Migration 004 set UTC on its own connection only. The old disposable verifier
  also set UTC independently, so its earlier results did not verify the production
  engine initializer.
- SQL-created users, reservations, payments and hotel partners have second-precision
  TIMESTAMP defaults. User/Reservation/Payment ORM mappings are DateTime and used
  host-local naive `datetime.now`. HotelPartner uses a server default.
- Event/adjustment SQL and ORM columns use DATETIME(6). Their Python defaults were
  already UTC-naive; server CURRENT_TIMESTAMP(6) still required UTC sessions.
  Signed quote epochs normalize to UTC before removing offsets. Settlement and
  reconciliation normalize aware clocks to UTC-naive storage; financial responses
  restore UTC awareness and serialize settlement with `Z`.
- Existing booking/payment/cancellation response contracts do not expose their
  legacy creation timestamps. Calendar DATE business rules remain unchanged.
  Session SQL mode was inherited, not initialized by application code.

## C. UTC session initialization implementation

`create_app_engine` installs one SQLAlchemy `connect` listener for MySQL dialect
engines, before first checkout. Each newly created physical connection executes
`SET SESSION time_zone = '+00:00'` through a DBAPI cursor, closed in `finally`.
Initialization failures propagate. There is no explicit commit/rollback, global
zone/mode change, credential logging, startup migration or per-checkout duplicate
initializer. New connections after invalidation/disposal/reconnect run the same
listener; ordinary pool reuse retains its initialized session.

`SessionLocal`, `get_db` and SQLite engine configuration are unchanged. Connection
retry/pre-ping policy is unchanged in production; the disposable runner's existing
pre-ping pool exercises replacement of a server-closed connection. Application
code must not change a pooled session's time zone afterward. Restart all workers
during rollout to replace old connections and defaults.

One shared `utc_now` helper now supplies UTC-naive defaults for future User,
Reservation and Payment inserts as well as existing ledger defaults. This prevents
future host-local naive values from being interpreted as UTC after the session
change. It does not update old records, alter column types or change pricing,
payment, cancellation, authentication or transaction policy.

## D. Legacy TIMESTAMP/DATETIME compatibility

Live synthetic users, bookings, original payments and cancellation payments were
written under known `-07:00` and `+05:30` sessions. UTC application reads returned
the same stored instants with UTC clock fields; UNIX_TIMESTAMP values remained
equal before/after read-only financial summaries. Historical fields were not
rewritten. The actual cancellation service also preserved old creation fields and
created its new Payment with a UTC default under a simulated non-UTC host clock.

DATETIME(6) literals remained unchanged when session offsets changed; TIMESTAMP(6)
display shifted with the session while its epoch stayed fixed. Legacy TIMESTAMP
columns retain their existing second precision; new DATETIME(6) settlement values
preserve microseconds. These observations agree with
[MySQL 5.7 temporal semantics](https://docs.oracle.com/cd/E17952_01/mysql-5.7-en/datetime.html).

For real legacy rows, an unknown original session zone/client clock prevents
proving that a stored instant or naive DATETIME represents the intended event.
UTC initialization cannot reconstruct that intent. Preserve stored epochs and
DATETIME literals, review known examples and client history in a restored copy,
and handle any corrections through a separately reviewed plan. There is no
invented backfill, conversion or automatic data migration here.

## E. Exact files changed

Production configuration/defaults:

- `backend/app/config/database.py`
- `backend/app/utilities/timestamps.py` (new)
- `backend/app/models/user.py`
- `backend/app/models/reservation.py`
- `backend/app/models/payment.py`
- `backend/app/models/reservation_change_event.py`
- `backend/app/models/reservation_change_adjustment.py`

Verification:

- `backend/tests/test_database_utc.py` (new)
- `backend/database/verification/run_mysql57_verification.py`
- `backend/database/verification/test_mysql57_utc.py` (new)

Documentation:

- `backend/README.md`
- `backend/US7.2_API_INTEGRATION.md` (historical-checkpoint notice)
- `backend/database/README.md`
- `backend/database/US7.2_TEAM_ROLLOUT.md` (new)
- `backend/database/US7.2_UTC_READINESS.md` (new)

Migration SQL, initialization SQL, business services, router contracts, frontend
files and environment files were not changed. Changes are left uncommitted.

## F. Focused tests

**6 offline UTC tests passed.** They cover listener registration without opening a
MySQL socket, cursor cleanup/error propagation, no initializer commits/rollbacks,
SQLite rollback/configuration and real ORM UTC defaults under two simulated
non-UTC host clocks. Explicit historical values survive unrelated updates.
The final combined offline check passed 6 tests and safely skipped 19 live cases
without the runner-supplied disposable context (0.63s).

## G. Live isolated MySQL results

**62 tests passed in 4.31s: 43 existing contract tests plus 19 UTC cases.** The runner now
creates test engines through the production factory and removes its former
duplicate UTC initialization/explicit engine-connect commit. Its separate admin
setup connections remain confined to the verified disposable server.

Docker access was denied by the ordinary Codex sandbox; the approved execution
path independently verified Docker Desktop 29.2.1 on Apple Silicon/arm64.
MySQL 5.7.44 ran successfully with explicit `linux/amd64` emulation. Each run used
a unique labeled container, tmpfs-only data, random loopback port, synthetic
credentials/records and an identity marker checked before DDL. Dotenv was disabled
and application configuration pointed to unusable synthetic endpoints. The runner
network audit allowed only its verified disposable MySQL port. It accepted no
development DB URL.

Coverage includes:

- Actual session `+00:00` on new and simultaneously checked-out connections,
  exactly one initializer per physical connection, and repeated pooled reuse.
- New connection after explicit invalidation and after the server closes an idle
  test connection; both replacements initialize UTC. Global zone stayed `SYSTEM`.
- DATETIME/TIMESTAMP round trips, UTC server defaults, legacy display/epoch
  compatibility and real cancellation defaults under a non-UTC host clock.
- Ten-minute quote expiry using aware clocks with differing offsets; no mutation
  or extra provider request on expiration.
- UTC quote/event/adjustment defaults and microsecond-preserving settlement
  round trips with aware UTC JSON/summary serialization.
- Pending DML remains invisible to a separate newly initialized connection and
  rolls back; failed settlement rolls back revision/status/timestamps together.
- Strict-mode differences, preserved global/session mode, cleaned probe tables,
  isolated sessions and no cross-test contamination.
- Existing fresh/pre-004 upgrade metadata, preserved synthetic records, FK and
  uniqueness behavior, InnoDB locking/races, receipt/ledger/cancellation contracts.

The final machine-readable evidence is
`/private/tmp/likehome-us72-utc-evidence-final.json`: 62 collected, 0 failed,
pytest exit 0, container removed/tmpfs discarded, existing container and volume
IDs preserved. That temporary evidence is local execution output; this report
records the durable result. Two early test assumptions were corrected to match
observed behavior: PyMySQL reports zero-date 1292 as OperationalError, and separately
evaluated timestamp defaults may differ by microseconds. No application check was
disabled to obtain a pass.

Reproduce from the repository root with Docker running:

```bash
backend/.venv/bin/python backend/database/verification/run_mysql57_verification.py \
  --disposable --evidence /private/tmp/likehome-us72-utc-evidence.json
```

## H. Full backend regression results

**875 passed in 21.24s**: the prior 869 plus 6 new offline UTC tests. Existing
booking/payment/cancellation/authentication/search/details/change and cross-feature
tests passed. Two existing Starlette/httpx and anyio BlockingPortal deprecation
warnings remain. Real providers were mocked and databases were isolated SQLite.
An audit hook rejected `socket.connect` and `socket.getaddrinfo`; dotenv was
disabled and synthetic unusable MySQL/provider settings supplied.

Reproduce the isolated full suite from the repository root:

```bash
cd backend
env PYTHON_DOTENV_DISABLED=1 DB_HOST=127.0.0.1 DB_PORT=1 \
  DB_NAME=us72_offline_tests DB_USER=us72_synthetic DB_PASSWORD=synthetic-test-only \
  API_KEY=synthetic-test-only EXTERNAL_API_URL=http://127.0.0.1:1 \
  JWT_SECRET_KEY=us72-isolated-test-key-32-characters .venv/bin/python - <<'PY'
import sys
import pytest

def forbid_network(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise AssertionError('Offline verification must not contact external services')

sys.addaudithook(forbid_network)
raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', 'tests']))
PY
```

For focused offline checks use `tests/test_database_utc.py` in the same command.
`git diff --check` and new-file whitespace/Python syntax checks passed.

## I. Team migration rollout procedure

The [operator runbook](US7.2_TEAM_ROLLOUT.md) covers all ten requested steps:
target/schema identification, read-only inspection, restore-tested backup, stop
all writers, applicable 001–004 order, schema/record verification, real application
UTC checks, isolated/backend smoke checks, partial-DDL failure handling and
financial-history retention. There is no migration tracker table; exact schema
objects establish milestones. Retarget reviewed operator copies where scripts
hardcode `USE likehome_db`. Fresh SQL initialization already contains 004 and
must not be followed by ALTER migrations. This procedure was not executed.

## J. UTC and strict-mode risks

UTC initialization does not fix incorrect host clocks or unknown old write
conventions. TIMESTAMP display changes are expected for previously non-UTC readers;
naive external consumers must be reviewed. Old pool connections require restart.
Named MySQL time-zone tables are unnecessary for the numeric `+00:00` offset.

The disposable default session mode was
`STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION`. Additional tests retained session mode
with NO_ZERO_DATE/NO_ZERO_IN_DATE, and separately tested non-strict mode. Strict
mode rejected DECIMAL overflow (1264); non-strict mode clipped to 99999999.99 with
a warning. Strict NO_ZERO_DATE rejected zero date (1292), while the other tested
modes accepted it. No global mode was changed. Actual team financial-write sessions
must pass strict-mode/data compatibility checks; do not silently weaken mode.
MySQL 5.7 CHECK clauses do not supply business validation.

## K. Development database preservation

No development/production connection, migration, data rewrite, real SerpApi/payment
request, `.env` edit or stack start occurred. Existing containers/volumes and the
separate frontend worktree were preserved. The runner removed every test-owned
container and discarded tmpfs data. The MySQL image downloaded for this task was
removed after verification; the original seven-image inventory was restored.
No main/feature commit, push or merge occurred.

## L. Remaining deployment blockers

Each target still needs its actual schema/engine/FK/data inventory, known legacy
timestamp review, strict application-session mode, stopped writers, verified
backup/restore rehearsal, approval, applicable migrations and updated-code UTC/
smoke preflight. None can be inferred from isolated fixtures. The existing frontend
clean-install/lint mismatch remains a separate stack-readiness issue; it was not
repaired. Main integration remains gated on the coordinated deployment prerequisites.

## M. Coordinated Migration 004 rollout readiness

**NOT READY to execute against existing team databases.** UTC implementation and
disposable verification are complete, and the rollout plan is prepared. Per-target
evidence and explicit rollout authorization remain required. Do not apply migrations,
start the updated stack on pre-004 databases or merge main based on this report alone.
