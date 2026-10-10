# Reservation change persistence (migration 004)

Increment 3B.1 supplies schema and mappings. Increment 3B.2A adds revision-aware
quotes, canonical money, Pay/cancellation revision increments and read-only
receipt recognition. Nothing applies migrations at startup. No final change
endpoint is registered. Increment 3B.2B adds the atomic confirmation service,
event consumption and primary charge/credit persistence. Increment 3B.3A adds
internal charge settlement and financial summaries. Increment 3B.3B extends the
existing cancellation transaction with internal ledger reconciliation and its
financial summary. ORM `create_all` does
not migrate tables. Migration 004 remains a manual prerequisite and must not be
applied to development MySQL by this increment.

## Schema and cancellation reconciliation

`reservations.revision` starts at zero. The date index supports existing owner
overlap/history queries. Events store committed receipts, hashes (not raw JWTs),
before/after revisions, dates, room IDs, exact obligations and reviewed context.
The quote format's `version` is not the reservation revision. Format 2 requires
a dedicated strict unsigned `reservation_revision` claim. Old-format reviews
must be replaced, never interpreted as revision zero. Expiry remains ten minutes.
Successful pending-to-paid and cancellation transitions increment revision once
inside their existing transactions; rejected/repeated operations do not. Failed
commits roll back the revision and financial transition together.

## Read-only idempotency recognition

The change receipt helper verifies signature, purpose, format and signed identity
before looking up an owner-scoped committed event by JTI. It checks SHA-256 of
the exact token and canonical confirmation input (dates, explicit acceptance,
cent-normalized prices and authenticated/path identity). Conflicting reuse is
HTTP 409. Matching receipts return a detached JSON copy without modifying rows.
Raw tokens are never logged or inserted. None means no receipt, not permission
to apply a quote. Reads cannot autoflush staged records or consume a quote.

An exact historical receipt can outlive quote expiry/current revision and dates.
`ReservationChangeReceiptRequest` is specifically a read-only historical input;
it is NEVER valid authorization for new writes. Normal confirmation and provider
request schemas still reject past dates. The signature decoder likewise is only
structural verification: new applications require full quote time/state checks.

## Atomic confirmation service (unregistered)

`reservation_change_service.confirm_reservation_change` accepts the existing
confirmation input and authenticated customer ID using a dedicated request
Session. It verifies active ownership and returns an exact committed receipt
before spending provider quota. New uses verify format-2 signature, revision,
fingerprint, signed reconfirmed destination/occupancy and price acknowledgements.
Historical receipt inputs must pass normal future-date validation before any new
application. No client hotel identity or financial value determines settlement.

One fresh trusted provider request runs before mutation locks. The service ends
the earlier read transaction, then locks User, Reservation, Payments ordered by
ID, and Adjustments ordered by ID. It refreshes authoritative state and repeats
receipt, eligibility, revision, fingerprint, property, expiry, acceptance and
overlap checks. Creation uses the same User serialization point; Pay/cancellation
serialize on the Reservation. Normal receipt lookup alone provides no such
concurrency guarantee.

Date/total/rate-association changes, one revision increment, event history and
any adjustment commit once in the same transaction. Rate records are reused or
created for the same Hotel using creation's rate-record convention; shared
RoomType prices are never modified. Pending booking payments are revised in
place. Paid booking payments remain untouched: increases add pending internal
charges, decreases add recorded reservation-specific credits, and zero differences
add no adjustment. All successful date changes add an event, including zero-price
changes. Later obligations come from the latest committed event. Earlier pending
or failed charges block new changes; credits are never silently netted against
them. Receipt and financial JSON amounts use fixed cent strings.

Event JTI and reservation/revision uniqueness are the final duplicate defenses.
After an identified event uniqueness failure, all candidate writes roll back;
only a matching committed token/request receipt permits a successful retry.
Unrelated integrity errors fail without being interpreted as successful retries.
Any other validation, deadlock or transaction failure also rolls back all writes.

Confirmation and adjustment settlement remain absent from the router. Backend
cancellation compatibility is now implemented; activating the full customer
workflow and frontend integration remain separate authorized increments.
Existing public booking APIs remain unchanged. The offline tests use mocked providers and
isolated SQLite; threaded tests simulate User-row waits with a Python mutex around
real Sessions. The separate [live verification report](US7.2_MIGRATION_004_VERIFICATION.md)
records bounded MySQL/InnoDB SQL-lock and service-race tests.

## Internal adjustment payment and summaries (unregistered)

`reservation_change_payment_service` provides owner-scoped adjustment detail,
`settle_reservation_change_charge`, and `get_reservation_financial_summary` for
later UI integration. The customer ID must come from existing `get_current_user_id`
authentication; no new JWT/role contract or public route is added. Adjustment
ownership follows Adjustment -> ChangeEvent -> Reservation -> active User, with
both event and reservation owner checked. Missing/nonowned entries share a 404.

Settlement requires explicit acceptance, a reviewed amount, and the reservation
revision. Client values are acknowledgements only. It ends the earlier read
transaction, then locks User -> Reservation -> Payments ascending ID -> Adjustments
ascending ID and reloads authoritative associations, status, amount and history.
Only primary internal charges on a confirmed reservation with a preserved paid
booking Payment may transition pending/failed -> paid. Failed internal charges
retry the same record; no additional Payment or adjustment is inserted. The
charge's amount must match its committed event's tax-inclusive obligation delta,
and its unsettled event must still be the latest change. New transitions require
the current acknowledged revision and increment it once with UTC `settled_at` and
`updated_at`, in one commit. Failures roll back revision/status/timestamps together.

Already-paid retries with the same cent-normalized amount return the paid record
without writing or incrementing revision, even with an older acknowledged
revision. Future revision acknowledgements or different amounts are conflicts.
That exception cannot authorize a new transition. The response uses the persisted
settlement timestamp and excludes a changing current-revision field; the summary
supplies the current revision for a subsequent review. Cancelled stays, voided
entries, credits, reconciliation entries, or inconsistent histories are rejected.
Completed stays cannot start a settlement, but an existing paid result is readable.
Settlement makes zero provider requests and records no bank/card activity.

Financial responses use numeric cent-normalized amounts, with Decimal arithmetic
internally. Summaries distinguish the current reservation total, latest committed
tax-inclusive stay obligation, original booking Payment record/status, paid,
pending and failed additional charges, recorded reservation credits, and adjustment
IDs/statuses. Outstanding additional amount is pending plus failed charges, with
no credit deduction and no booking Payment double counting. An original pending
Payment can already carry its revised amount; this is not described as a frozen
original price. No net cash balance, spendable credit, reward value or external
refund is inferred. Ledger amounts are validated against immutable change events.

Cancelled reservations can now be summarized when cancellation charge and ledger
treatment are consistent. Incomplete legacy cancellations still return a safe
conflict. The existing stay-obligation field remains a historical stay cost, not
a cancellation balance. Migration 004 remains unapplied to development MySQL.
The offline suite uses SQLite/mutexes; bounded live results are in the verification report.

## Atomic cancellation reconciliation (3B.3B)

The existing public cancellation service performs an owned initial read, ends the
earlier transaction, then locks active User -> owned Reservation -> Payments
ascending ID -> Adjustments ascending ID with authoritative ORM refresh. Existing
payment ambiguity, ownership, confirmed-status and duplicate-cancellation guards
remain. A duplicate cancellation still returns HTTP 409. Ordinary cancellation
retains its original Payment record: unpaid booking status stays pending, paid
booking status becomes the existing internal `refunded` marker, and the booking
amount never changes. This marker does not describe an external bank refund.

For changed reservations, the event chain and ledger must validate before any
cancellation mutation. Pending/failed primary charges become voided and cannot be
settled later. Their amounts, event relationships, creation times and unset
settlement timestamps are preserved; only status and UTC updated time change.
Paid primary charges remain completely unchanged and get one equal-amount linked
`cancellation_reconciliation` credit with status `recorded`. Recorded primary
credits remain completely unchanged and get one equal-amount linked recorded
debit, superseding their reservation-specific effect without collecting money.
Reversals have no settlement timestamp, are not account balances, and cannot be
settled through the internal charge service. Parent/change/owner, opposite kind,
equal amount, primary role, and uniqueness guards prevent duplicate or unrelated
compensation. No reconciliation is created for a voided, never-paid charge.

The cancellation charge remains a separate pending Payment: current reservation
total times the existing 20% rate. Decimal cent normalization aligns the amount
and response with DECIMAL(10,2); no fee/base/tax/service-fee policy changes. A zero
cent fee is represented as zero, not an invented positive charge. There is one
revision increment and one commit for all voids, reversals, reservation/payment
status changes and cancellation Payment creation. Any failure rolls back them all.
Reconciliation helpers stage records without independently committing, and
cancellation never calls SerpApi. Existing settlement and change operations use
compatible locks; cancelled/voided charges cannot generate later payments.

Financial summaries keep all original fields and add voided-charge totals,
explicit linked cancellation reconciliations, reconciliation credit/debit totals,
the cancellation Payment, and separate outstanding booking/cancellation amounts.
Primary adjustments and reversals are separate lists and separate buckets.
Historical paid charges and recorded credits remain visible; recorded reversals
are neither payments received nor collectible charges. A cancelled stay has zero
outstanding booking/change obligations; its pending cancellation fee is reported
only as an outstanding cancellation obligation. No credits, reversals or original
booking funds are silently netted against that fee, and no net payout is inferred.

Read validation rejects missing/contradictory reversals, cross-event parents,
altered amounts, paid-history rewrites, collectible charges after cancellation,
or missing/mismatched cancellation payments. Public cancellation responses keep
their fields and numeric types. Confirmation, adjustment settlement, and summary
routes remain unregistered. No frontend, JWT, provider, migration or real-database
changes are part of that implementation increment. Its contention tests use isolated
SQLite with explicitly simulated row waits. The later disposable verification
also exercises real MySQL/InnoDB waits and focused application-service races.

Two small additions keep reconciliation within the adjustment table:

- `entry_role`: `price_change` or `cancellation_reconciliation`.
- `reconciles_adjustment_id`: optional reference to the original adjustment.

`UNIQUE(change_id, entry_role)` allows one primary adjustment and one compensating
entry per change. The unique parent reference prevents duplicate reconciliation.
The composite self-FK requires parent and child to belong to the same change.
No third ledger table or new Payment type is introduced.

Cancellation can void a pending/failed charge, retain a paid charge and record
a compensating credit, or retain a recorded credit and record a compensating
debit. Reconciliation entries use `recorded` status and cannot be collected as
new pending payments. These are internal records, not bank refunds or spendable
funds. The cancellation helper now applies these equal-and-opposite reversals.

MySQL 5.7 CHECK enforcement is not used. The persistence input schema
`ReservationChangeAdjustmentRecord` validates positive, finite cent amounts,
categories, statuses and required parent references. Future writers MUST also
lock and validate the parent is a primary entry, belongs to this change, has the
opposite kind and an approved compensating amount. They must prevent self-links,
reconciliation chains, updates to immutable event receipts and raw JWTs in JSON.
SQL uniqueness/FKs alone do not establish these business relationships.

This supports one cancellation reconciliation per primary adjustment; its amount
must follow the approved reconciliation rules. Multiple staged reconciliation
entries would require a separately approved schema expansion and are not needed
by the approved cancellation policy described here.

The confirmation service derives the event's user, booking payment and old/new
room associations from the locked owned reservation. Future writers must retain
these guards. The FKs establish
that records exist, not that a supplied payment belongs to the supplied stay.

## Money and UTC

New history/ledger money uses ORM Numeric(10,2)/Decimal and SQL DECIMAL(10,2).
Compare revised payment obligations (including tax), not reservation totals.
Fingerprint money and signed quote prices use fixed two-decimal strings via the
existing cent rounding helper. The signed review and numeric quote response use
the same normalized amounts. Confirmation hashes also normalize cents, so
floating-point representation artifacts do not cause false conflicts. Decimal
fingerprints are supported without converting existing ORM money fields.
Store JSON monetary snapshots as canonical decimal strings or integer cents;
plain JSON cannot encode Decimal directly. Convert to numeric values only at
existing API serialization boundaries where that contract requires it.

Existing Reservation/Payment/RoomType Float mappings remain unchanged in this
increment. Cancellation currently multiplies by a float fee; changing the ORM
types alone would break that existing operation. A coordinated future step must
align the mappings with existing arithmetic/API serialization together;
do not partially convert these fields. Existing SQL already uses DECIMAL(10,2),
so the normal SQL-created database needs no monetary column conversion.

All new timestamps use DATETIME(6), interpreted as UTC. ORM generated timestamps
use UTC; SQL defaults require a UTC session. Future writers must normalize aware
quote times to UTC before removing the offset for MySQL DATETIME, and explicitly
update `updated_at`. There is no automatic settlement-time behavior. A manually
run migration setting time_zone affects only that connection, not application
connections. Connection-wide UTC initialization is future integration work.

## Before application (manual only)

1. Back up schema AND data with a tested restoration procedure. Stop booking
   writes and deploy in a maintenance window: MySQL DDL commits implicitly.
2. Inspect `SELECT VERSION(), @@sql_mode, @@session.time_zone;` in the intended
   disposable/staging environment first. Require MySQL 5.7.8+ for JSON, InnoDB,
   compatible DATETIME(6) support and strict SQL mode for financial writes.
3. Inspect SHOW CREATE TABLE for users, hotels, room_types, reservations and
   payments. Referenced IDs must be signed INT primary keys and tables InnoDB.
   Confirm money is DECIMAL(10,2) and prerequisites 001-003 are present.
4. Check for orphaned reservation/payment/room associations and duplicate booking
   payments. Preserve existing records; resolve anomalies separately instead of
   deleting/backfilling fabricated history. New tables are empty, so duplicate
   old payments do not themselves prevent this DDL, but remain ineligible.
5. Confirm revision, ix_reservations_user_dates and both new tables/constraint
   names do not already exist. If a prior DDL attempt partially succeeded, inspect
   each object before recovery; do not blindly rerun or use IF NOT EXISTS to hide
   a conflicting schema. Check teammate migrations before assigning another ID.

## Order

- Existing database: apply missing 001, 002 and 003 only as applicable, in order;
  then run 004_add_reservation_change_persistence.sql once. Follow each earlier
  migration's fresh/existing-database instructions.
- Fresh database: use like_home_database_init.sql only. It contains the final
  definitions, not ALTER statements; do not also run 001-004.
- Apply the schema before deploying the new Reservation mapping: it selects the
  revision column. Running new code on the old database will fail, even though
  no mutation endpoint is added. Never substitute startup `create_all`.

## Verification

The [2026-10-10 verification report and runbook](US7.2_MIGRATION_004_VERIFICATION.md)
records 43 passing live MySQL 5.7.44 tests and 734 passing offline backend tests.
The isolated database-readiness gate is READY; development migration and endpoint
activation remain separate steps. No development database was contacted.

The opt-in runner creates and removes its own labeled amd64 container, uses tmpfs
data and a random loopback-only port, verifies identity before DDL, and rejects
connections outside that container. It accepts no application DB URL. From the
repository root, with Docker Desktop running:

```bash
backend/.venv/bin/python backend/database/verification/run_mysql57_verification.py \
  --disposable --evidence /private/tmp/likehome-us72-mysql57-evidence.json
```

This validates both the repository-backed pre-004 upgrade and the fresh SQL
installation, with synthetic records only. The normal backend suite remains
`cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider tests`.

After manual application, inspect SHOW CREATE TABLE/SHOW INDEX and verify:

- Original IDs, dates, totals, payment amounts/statuses and row counts match the
  backup. All previously existing revisions are zero; both new tables are empty.
- Revision is unsigned, non-null, default zero; user/date index has correct order.
- New tables are InnoDB; event quote/revision uniqueness, role/parent uniqueness
  and restrictive FKs match migration 004; JSON and DATETIME precision match.
- In disposable tests only: reject duplicate quote IDs/revisions/primary entries,
  orphan references and cross-change reconciliation links. Confirm Decimal cents,
  UTC timestamps and rollback leave no partial event/ledger rows.
- Rerun the backend suite. SQLite tests and compiled MySQL DDL are useful contract
  checks, not proof of live MySQL migration execution or InnoDB locking.

## Rollback and history retention

Before any events/adjustments exist, stop new code, retain a backup, and remove
adjustments first, then events, then the new index/revision column. Confirm no
successful change/revision writes exist before treating this as a safe rollback.
DDL rollback requires explicit recovery steps; ordinary ROLLBACK cannot undo it.

Once history exists, disable future mutation and preserve/export event receipts,
charges and credits. Do not drop this ledger or reset revisions as an operational
rollback: that would lose financial obligations and successful idempotency keys.
RESTRICT references intentionally prevent hard deletion of recorded history's
users, reservations, payments and rooms. Existing account deletion is soft deletion.

## Validation boundary

The normal schema tests use isolated SQLite with FK enforcement, metadata checks
and MySQL-dialect DDL compilation. The separate Docker-owned runner verifies the
live MySQL contract and skips unless its explicit disposable context is supplied.
Development MySQL connections/migrations, real provider requests and external
financial transactions are outside this verification's authorization.
