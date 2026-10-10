import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { bookingRequestFromQuote } from "../lib/checkout.ts";

const contract = JSON.parse(readFileSync(new URL("../../../contract-fixtures/search-to-booking.json", import.meta.url)));

test("frontend booking builder matches the shared FastAPI contract fixture", () => {
  assert.deepEqual(
    bookingRequestFromQuote(contract.selection, contract.quote, contract.guest),
    contract.booking_request,
  );
});

test("shared contract keeps provider identity and authoritative quote values separate", () => {
  assert.equal(contract.selection.property_token, contract.quote.property_token);
  assert.equal(contract.booking_request.hotel_token, contract.quote.property_token);
  assert.equal(contract.booking_request.price_per_night, contract.quote.current_price_per_night);
  assert.equal(contract.booking_request.accepted_payment_amount, contract.quote.likehome_payment_amount);
  assert.ok(!("user_id" in contract.booking_request));
  assert.ok(!("total_price" in contract.booking_request));
  assert.ok(!JSON.stringify(contract.booking_request).includes("api_key"));
});
