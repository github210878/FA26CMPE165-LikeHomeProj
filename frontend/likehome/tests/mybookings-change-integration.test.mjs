
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const pageSource = readFileSync(
    new URL("../components/MyBookingsExperience.tsx", import.meta.url),
    "utf8"
);

const flowSource = readFileSync(
    new URL("../components/ReservationChangeFlow.tsx", import.meta.url),
    "utf8"
);

test("MyBookings imports the reservation change flow", () => {
    assert.match(
        pageSource,
        /import ReservationChangeFlow from ["']@\/components\/ReservationChangeFlow["']/
    );
});

test("only confirmed bookings receive the Change Booking control", () => {
    assert.match(pageSource, /booking\.status === ["']confirmed["']/);
    assert.match(pageSource, /Change Booking/);
});

test("the Change Booking button toggles the selected reservation", () => {
    assert.match(pageSource, /setChangingReservationId/);
    assert.match(
        pageSource,
        /changingReservationId === booking\.reservation_id/
    );
});

test("reservation confirmation stays disabled on MyBookings", () => {
    assert.match(
        pageSource,
        /enableConfirmation=\{false\}/
    );
});

test("the change flow requires explicit confirmation opt-in", () => {
    assert.match(
        flowSource,
        /enableConfirmation\s*=\s*false/
    );
    assert.match(flowSource, /enableConfirmation/);
});

test("MyBookings still includes the cancellation flow", () => {
    assert.match(pageSource, /canCancelBooking/);
    assert.match(pageSource, /cancelBookingAndRefresh/);
});

test("MyBookings TypeScript component parses without syntax errors", () => {
    const parsed = ts.createSourceFile(
        "MyBookingsExperience.tsx",
        pageSource,
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX
    );

    assert.equal(parsed.parseDiagnostics.length, 0);
});
