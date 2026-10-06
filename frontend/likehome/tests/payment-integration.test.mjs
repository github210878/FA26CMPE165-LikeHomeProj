import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../lib/api.ts";
import { getMyPayments, getPaymentDetails, payBookingPayment } from "../lib/bookings.ts";
import { createBookingSubmissionGuard } from "../lib/checkout.ts";
import { bookingPaymentForReservation, paymentHref } from "../lib/payment.ts";
import { saveAccessToken } from "../lib/token-storage.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
afterEach(() => { globalThis.fetch = originalFetch; globalThis.window = originalWindow; });

function session() {
  const entries = new Map();
  globalThis.window = { sessionStorage: {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  } };
  saveAccessToken("private-test-token");
}

const pending = { payment_id: 11, reservation_id: 42, amount: 374.22,
  payment_type: "booking", payment_status: "pending" };
const paid = { ...pending, payment_status: "paid" };

test("payment review reads persisted amount and pay uses only the returned ID", async () => {
  session();
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    if (url.endsWith("/get-payment-details/11")) return new Response(JSON.stringify(pending));
    if (url.endsWith("/pay/11")) return new Response(JSON.stringify(paid));
    throw new Error("Unexpected request");
  };
  assert.equal(paymentHref(11), "/payment/11");
  assert.deepEqual(await getPaymentDetails(11), pending);
  assert.deepEqual(await payBookingPayment(11), paid);
  assert.deepEqual(calls.map(({ url }) => new URL(url).pathname),
    ["/bookings/get-payment-details/11", "/bookings/pay/11"]);
  assert.equal(calls[0].init.headers.Authorization, "Bearer private-test-token");
  assert.equal(calls[1].init.headers.Authorization, "Bearer private-test-token");
  assert.equal(calls[1].init.method, "POST");
  assert.equal(calls[1].init.body, undefined);
  assert.equal(calls[1].init.headers["Content-Type"], undefined);
  assert.ok(calls.every(({ url }) => !url.includes("private-test-token") && !url.includes("user_id")));
});

test("network failure stays on the same payment and refresh discovers committed paid state", async () => {
  session();
  const calls = [];
  let serverPaid = false;
  globalThis.fetch = async (url) => {
    const path = new URL(url).pathname;
    calls.push(path);
    if (path === "/bookings/get-payment-details/11") return new Response(JSON.stringify(serverPaid ? paid : pending));
    if (path === "/bookings/pay/11") {
      serverPaid = true;
      throw new TypeError("Connection interrupted after commit");
    }
    throw new Error("Unexpected request");
  };
  assert.deepEqual(await getPaymentDetails(11), pending);
  await assert.rejects(payBookingPayment(11), TypeError);
  assert.deepEqual(await getPaymentDetails(11), paid);
  assert.deepEqual(calls, ["/bookings/get-payment-details/11", "/bookings/pay/11", "/bookings/get-payment-details/11"]);
});

test("pending payment can be recovered from owned payment list", async () => {
  session();
  globalThis.fetch = async () => new Response(JSON.stringify([pending,
    { payment_id: 12, reservation_id: 42, amount: 42, payment_type: "cancellation", payment_status: "pending" }]));
  const payments = await getMyPayments();
  assert.deepEqual(bookingPaymentForReservation(payments, 42), pending);
  assert.equal(bookingPaymentForReservation(payments, 99), null);
  assert.equal(paymentHref(bookingPaymentForReservation(payments, 42).payment_id), "/payment/11");
});

test("double submission guard and malformed payment responses fail safely", async () => {
  session();
  const guard = createBookingSubmissionGuard();
  assert.equal(guard.tryStart(), true);
  assert.equal(guard.tryStart(), false);
  guard.finish();
  assert.equal(guard.tryStart(), true);
  globalThis.fetch = async () => new Response(JSON.stringify({ ...paid, amount: "374.22" }));
  await assert.rejects(getPaymentDetails(11), /unexpected response/);
  await assert.rejects(payBookingPayment(11), /unexpected response/);
  globalThis.fetch = async () => new Response("private failure", { status: 409 });
  await assert.rejects(payBookingPayment(11), (error) => error instanceof ApiError && error.status === 409 && !error.message.includes("private"));
  await assert.rejects(payBookingPayment(0), /Invalid payment ID/);
});
