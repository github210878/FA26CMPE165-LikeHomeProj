# Reservation change persistence (migration 004)

Increment 3B.1 supplies schema and mappings. Increment 3B.2A adds revision-aware
quotes, canonical money, Pay/cancellation revision increments and read-only
receipt recognition. Nothing applies migrations at startup. No final change
endpoint is registered. Increment 3B.2B adds the atomic confirmation service,
event consumption and primary charge/credit persistence. Adjustment settlement
and cancellation ledger reconciliation remain deferred. ORM `create_all` does
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

The service is deliberately absent from the router: existing payment/cancellation
flows cannot settle or reconcile these new adjustments yet. Increment 3B.3 must
finish those approved financial policies before enabling customer confirmation.
Existing public booking APIs remain unchanged. Tests use mocked providers and
isolated SQLite; threaded tests simulate User-row waits with a Python mutex around
real Sessions. No real MySQL/InnoDB concurrency verification has occurred.

Two small additions keep reconciliation within the adjustment table:

- `entry_role`: `price_change` or `cancellation_reconciliation`.
- `reconciles_adjustment_id`: optional reference to the original adjustment.

`UNIQUE(change_id, entry_role)` allows one primary adjustment and one compensating
entry per change. The unique parent reference prevents duplicate reconciliation.
The composite self-FK requires parent and child to belong to the same change.
No third ledger table or new Payment type is introduced.

A future cancellation can void a pending charge, retain a paid charge and record
a compensating credit, or retain a recorded credit and record a compensating
debit. Reconciliation entries use `recorded` status and cannot be collected as
new pending payments. These are internal records, not bank refunds or spendable
funds. Schema support does not calculate amounts or perform any reconciliation.

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

First provision an explicitly approved disposable MySQL 5.7 database. Validate
both fresh installation and upgrading a copy with existing reservations/payments.
No such database was provisioned or contacted in this increment.

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

Automated schema tests use isolated SQLite with FK enforcement, metadata checks
and MySQL-dialect DDL compilation. No actual development MySQL connection,
migration execution, provider request or financial transaction is authorized.
