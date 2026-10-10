# US7.2 backend API integration

Source integration is complete; **development deployment is NOT READY**.
The updated stack was not started. Development MySQL, environment files,
containers and the separate frontend worktree were not accessed for mutation.
Migration 004 remains unapplied to development. This report supplements the
[completed isolated MySQL checkpoint](database/US7.2_MIGRATION_004_VERIFICATION.md).

| Item | Result |
| --- | --- |
| A. Initial Git state | Clean `feature/reservation-change`, HEAD `4c86e3b` (`test: verify reservation change migration on MySQL 5.7`). No branch switch, commit, push, merge or rebase. The separate frontend worktree was preserved. |
| B. Inspected contracts | Booking/hotel/main routers; confirmation, quote validation, idempotency, settlement, summaries and cancellation services; ownership DAO joins; receipt/payment/summary/cancellation schemas; customer/partner JWT dependencies; engine/session configuration; DATETIME mappings; migration report; existing HTTP/service tests and OpenAPI registration. |
| C. Confirmation | `POST /bookings/{reservation_id}/change-confirm` delegates to `confirm_reservation_change`. Positive path ID, typed signed-quote acknowledgement, explicit acceptance, and a typed exact committed receipt. |
| D. Adjustment payment | `POST /bookings/{reservation_id}/adjustments/{adjustment_id}/pay` uses the owner-scoped adjustment → event → reservation → active-user join and checks the reservation in the URL before delegating to `settle_reservation_change_charge`. Persisted charge amount remains authoritative. |
| E. Summary | `GET /bookings/{reservation_id}/financial-summary` delegates to `get_reservation_financial_summary`, retaining numeric money, original payment, charge/credit buckets, voided charges and cancellation reconciliation. |
| F. Authentication/ownership | Existing bearer dependency enforces active customers and session versions. Partner JWTs are rejected. Missing and nonowned resources share 404 errors. Request schemas reject client user/property identities and extra fields. No router commits or new lock order. |
| G. Idempotency | Confirmation returns the stored receipt for identical requests even after quote expiry, past stay dates, subsequent revisions or cancellation. Unconsumed requests still pass full future-date/service validation. Paid settlement retries return the original settlement without creating Payments, calling providers or writing again. |
| H. Errors/responses | 401 with Bearer challenge; nonowned/missing/path-mismatched resources 404; invalid typed input 422; stale/tampered/expired/conflicting reviews and unsupported ledger transitions 409; established provider 502/504; safe service failures 500. New-route validation errors contain only location/message/type, omitting request input and context. Receipt money preserves canonical cent strings; settlement/summary money remains JSON numbers. No raw quote in confirmation responses or new logging. |
| I. UTC | Application-written change timestamps normalize UTC before storing naive DATETIME(6); settlement serialization restores UTC and returns an aware ISO timestamp. Engine session UTC is not configured. Migration `SET time_zone` covers only its connection. Required follow-up configuration and legacy effects are described below; no live UTC correctness claimed. |
| J. Changed files | Exact list below. Only routes, narrow receipt response schemas, explanatory service/schema comments, HTTP tests, registration expectations and documentation changed. No service transaction or pricing policy changed. |
| K. Focused API tests | **82 passed**, using real authentication and services, isolated SQLite, mocked SerpApi, and deterministic quote clocks. |
| L. Full backend tests | **816 passed in 19.51s**, comprising the previous 734 tests plus 82 new HTTP tests; two existing deprecation warnings. |
| M. Regressions | Existing search/create/pay/cancel/quote/auth tests remain in the full suite. Prior route-absence assertions now verify registration and authentication. OpenAPI tests verify typed bodies/responses, positive path IDs, Bearer security, unique methods/paths and preserved existing paths. |
| N. Development isolation | All test commands disable dotenv and supply unusable synthetic MySQL/provider configuration. A Python audit hook rejects `socket.connect` and `socket.getaddrinfo`. Database writes are restricted to test-created SQLite engines. No development connection or updated server start occurred; no migration, environment-file or Docker changes. |
| O. Blockers | Development needs separately authorized Migration 004 deployment plus verified UTC session configuration, appropriate strict mode and legacy timestamp review. SQLite HTTP tests do not replace live stack integration. The previous 43-test disposable MySQL checkpoint was preserved and not rerun. |
| P. Development deployment | **NOT READY.** Source registration and passing isolated tests do not authorize running on the unmigrated development database. |
| Q. Next increment | Deployment readiness: implement and verify MySQL session UTC initialization in isolation, review legacy timestamp effects, then perform a separately authorized migration and stack preflight. This recommendation was not started; frontend work was not started. |

## Public contracts

All three routes use the existing `get_db` and `get_current_user_id` dependencies.
They return HTTP 200 for success and exact successful retries. The services retain
User → Reservation → Payments → Adjustments locking and their atomic commits.

Confirmation accepts the existing `ReservationChangeReceiptRequest` contract:

```json
{
  "check_in_date": "2026-11-04",
  "check_out_date": "2026-11-06",
  "quote_id": "<signed quote from change-quote>",
  "accept_quote": true,
  "price_per_night": 80,
  "accepted_payment_amount": 181.44
}
```

These prices acknowledge the signed review; fresh trusted provider data and the
service determine authoritative pricing. `ReservationChangeReceiptResponse`
returns the stored event/room/payment IDs, dates, revision, cent-string totals
and difference, plus an optional charge/credit receipt. Its adjustment status
describes the original confirmation, even when settlement later changes status.
Use financial-summary for the current ledger. Historical retries must reach the
service before future-date validation; every unconsumed quote is still validated
with `ReservationChangeConfirmRequest` before any mutation.

Adjustment payment accepts `AdjustmentSettlementRequest`:

```json
{
  "accepted_amount": 81.44,
  "reservation_revision": 1,
  "accept_payment": true
}
```

The URL's reservation must equal the adjustment's persisted reservation, even
when the customer owns both reservations. Its `AdjustmentSettlementResponse`
includes the existing adjustment/event/reservation IDs, numeric amount, paid
status and UTC settlement timestamp. Already-paid retries can acknowledge an
older revision for the same amount; future revisions remain conflicts. Credits,
voided charges, cancelled reservations and unsupported transitions cannot be paid.
This records an internal payment; no processor transaction or new booking Payment
is created.

Financial-summary has no request body and returns the existing
`ReservationFinancialSummary`. Credits remain recorded reservation-specific
history; they are not cash refunds or wallet funds. Paid/pending/failed/voided
charges, reconciliation credits/debits and original/cancellation Payments remain
separate. HTTP tests observe no INSERT/UPDATE/DELETE/REPLACE or provider calls
during summary reads.

## UTC deployment inspection and proposed follow-up

`app/config/database.py` currently calls `create_engine(DATABASE_URL)` without
session initialization. Nothing in `get_db` sets or verifies `@@session.time_zone`.
The migration's `SET time_zone = '+00:00'` does not initialize application pool
connections. The previous isolated MySQL tests explicitly initialized UTC; they
do not establish development session defaults.

The new event/adjustment models use MySQL DATETIME(6), Python UTC-naive defaults
and server `CURRENT_TIMESTAMP(6)` defaults. Signed issue/expiry epochs convert to
UTC before removing their offsets. Settlement and reconciliation timestamps use
aware UTC clocks, then remove offsets for storage. Financial response `_timestamp`
interprets naive stored values as UTC and normalizes aware values to UTC.
DATETIME does not convert time zones: non-UTC server defaults would produce values
that the response incorrectly interprets as UTC.

For this application's `mysql+pymysql` engine, the minimal proposed change is:

```python
engine = create_engine(
    DATABASE_URL,
    connect_args={"init_command": "SET SESSION time_zone = '+00:00'"},
)
```

**This snippet is documentation only; it was not applied.** It would initialize
each new physical PyMySQL connection, including new connections created after pool
recycling. The numeric offset avoids a dependency on MySQL's named-zone tables.
It makes server CURRENT_TIMESTAMP defaults UTC and MySQL TIMESTAMP reads/writes
use UTC. Existing DATETIME values and calendar DATE fields are not rewritten.
Verify session time zone on new and pooled connections and a DATETIME(6)
server-default/settlement round trip before deployment.

Legacy User/Reservation/Payment models use host-local `datetime.now`, and legacy
SQL timestamps/mappings differ as documented in the migration checkpoint. Session
UTC initialization alone does not repair or establish the meaning of old naive
values. MySQL TIMESTAMP presentation and naive client-write interpretation can
change relative to previously non-UTC sessions. Review those effects with known
fixtures in isolation; a broad timestamp/data migration remains outside this
increment. No application or database UTC configuration was changed here.

## Exact changed files

- `backend/app/routers/booking_router.py`
- `backend/app/schemas/reservation_change_schema.py`
- `backend/app/schemas/reservation_change_payment_schema.py` (comment only)
- `backend/app/services/reservation_change_service.py` (comment only)
- `backend/app/services/reservation_change_payment_service.py` (comment only)
- `backend/tests/test_reservation_change_api.py` (new)
- `backend/tests/test_reservation_change_confirmation.py`
- `backend/tests/test_reservation_change_payment.py`
- `backend/tests/test_reservation_change_quotes.py`
- `backend/tests/test_reservation_change_validation.py`
- `backend/README.md`
- `backend/US7.2_API_INTEGRATION.md` (new)

## Validation

Focused command: existing `backend/.venv/bin/python` running pytest
`-q -p no:cacheprovider tests/test_reservation_change_api.py`: **82 passed in 4.79s**.
Full command uses the same interpreter and flags with `tests`. Both commands use
the isolation and socket-audit controls described above. The two existing
Starlette/httpx and anyio BlockingPortal deprecation warnings remain.
Full suite: **816 passed in 19.51s**, with the same two existing warnings.
`git diff --check` passed. Explicit whitespace checks for both new files passed
(no trailing spaces, carriage returns or missing final newline).
No production integration testing occurred.
