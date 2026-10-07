import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { afterEach, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

import { ApiError } from "../lib/api.ts";
import { checkoutPriceBreakdown } from "../lib/checkout-pricing.ts";
import { createBookingSubmissionGuard, revalidateHotel, submitAcceptedQuote } from "../lib/checkout.ts";
import { normalizedGuestInformation, validateGuestInformation } from "../lib/guest-information.ts";
import { paymentHref } from "../lib/payment.ts";
import { saveAccessToken } from "../lib/token-storage.ts";

const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
afterEach(() => { globalThis.fetch = originalFetch; globalThis.window = originalWindow; });

const selection = {
  property_token: "property-123", q: "San Jose hotels",
  check_in_date: "2026-11-01", check_out_date: "2026-11-03",
  adults: 2, children: 0, currency: "USD", gl: "us", hl: "en",
  displayed_price_per_night: 999,
};
const quote = {
  property_token: selection.property_token, hotel_name: "Test Hotel",
  check_in_date: selection.check_in_date, check_out_date: selection.check_out_date,
  adults: 2, children: 0, currency: "USD", number_of_nights: 2,
  availability: "available", rate_rule: "lowest_eligible_provider_base_total",
  source: "Provider A", guest_capacity: 2, current_price_per_night: 100,
  provider_base_total: 200, provider_total_with_taxes_fees: 230,
  likehome_reservation_total: 210, likehome_payment_amount: 226.80, price_changed: true,
};
const guest = { guest_full_name: "Person Example", guest_email: "person@example.com" };

test("disclosed components use the authoritative backend example and preserve the quote", () => {
  const immutableQuote = Object.freeze({ ...quote });
  assert.deepEqual(checkoutPriceBreakdown(immutableQuote), {
    baseStayTotal: 200, serviceFee: 10, tax: 16.80, finalTotal: 226.80,
  });
  assert.deepEqual(immutableQuote, quote);
});

test("display amounts follow returned totals rather than fixed percentages or nightly multiplication", () => {
  assert.deepEqual(checkoutPriceBreakdown({
    ...quote, current_price_per_night: 123, provider_base_total: 200,
    likehome_reservation_total: 217.43, likehome_payment_amount: 251.61,
  }), { baseStayTotal: 200, serviceFee: 17.43, tax: 34.18, finalTotal: 251.61 });
  assert.deepEqual(checkoutPriceBreakdown({ ...quote, likehome_reservation_total: 200, likehome_payment_amount: 200 }), {
    baseStayTotal: 200, serviceFee: 0, tax: 0, finalTotal: 200,
  });
});

test("cent subtraction avoids floating point subtraction artifacts", () => {
  assert.deepEqual(checkoutPriceBreakdown({
    provider_base_total: 1.03, likehome_reservation_total: 1.08, likehome_payment_amount: 1.17,
  }), { baseStayTotal: 1.03, serviceFee: 0.05, tax: 0.09, finalTotal: 1.17 });
  assert.deepEqual(checkoutPriceBreakdown({
    provider_base_total: 99999900, likehome_reservation_total: 99999950.01, likehome_payment_amount: 99999999.99,
  }), { baseStayTotal: 99999900, serviceFee: 50.01, tax: 49.98, finalTotal: 99999999.99 });
});

// Reuse the Node runner's TSX-transpilation approach. Seed the trusted, ready
// checkout state; mount effects are disabled so these tests focus on presentation
// and the actual booking handlers, with every HTTP response mocked.
const require = createRequire(import.meta.url);
function checkoutHarness(initialQuote) {
  const slots = ["ready", initialQuote, "", "", { ...guest }, {}];
  const navigation = [];
  let cursor = 0;
  const hooks = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value) => {
        slots[index] = typeof value === "function" ? value(slots[index]) : value;
      }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback: (callback) => callback,
    useEffect: () => {},
  };
  const imports = {
    react: hooks,
    "next/link": { default: ({ children, href, className }) => createElement("a", { href, className }, children) },
    "next/navigation": { useRouter: () => ({ replace: (href) => navigation.push(href) }) },
    "@/components/AuthProvider": { useAuth: () => ({ status: "authenticated", invalidateSession: () => {} }) },
    "@/lib/api": { ApiError },
    "@/lib/payment": { paymentHref },
    "@/lib/checkout": { createBookingSubmissionGuard, revalidateHotel, submitAcceptedQuote },
    "@/lib/checkout-pricing": { checkoutPriceBreakdown },
    "@/lib/guest-information": { normalizedGuestInformation, validateGuestInformation },
  };
  const source = readFileSync(new URL("../app/checkout/checkout-experience.tsx", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  });
  const loadedModule = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (name) => Object.hasOwn(imports, name) ? imports[name] : require(name), loadedModule, loadedModule.exports,
  );
  return {
    navigation,
    render() {
      cursor = 0;
      const tree = loadedModule.exports.default({ selection });
      const nodes = [];
      function visit(node) {
        if (Array.isArray(node)) return node.forEach(visit);
        if (!node || typeof node !== "object") return;
        nodes.push(node);
        visit(node.props?.children);
      }
      function content(node) {
        if (Array.isArray(node)) return node.map(content).join("");
        if (node && typeof node === "object") return content(node.props?.children);
        return node == null ? "" : String(node);
      }
      visit(tree);
      const rows = new Map();
      for (const node of nodes) {
        const children = node.props?.children;
        if (node.type === "div" && Array.isArray(children) && children[0]?.type === "dt" && children[1]?.type === "dd") {
          rows.set(content(children[0]), content(children[1]));
        }
      }
      return {
        rows, nodes, html: renderToStaticMarkup(tree),
        reserve: nodes.find((node) => node.type === "button" && node.props.children === "Reserve and continue to payment"),
      };
    },
  };
}

test("checkout renders currency-safe semantic breakdown and preserves nightly, nights, reference and demo wording", () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; throw new Error("Unexpected request"); };
  const harness = checkoutHarness(quote);
  const view = harness.render();
  assert.equal(view.rows.get("Stay subtotal"), "$200.00");
  assert.equal(view.rows.get("LikeHome service fee"), "$10.00");
  assert.equal(view.rows.get("Tax"), "$16.80");
  assert.equal(view.rows.get("Final booking total"), "$226.80 USD");
  assert.equal(view.rows.get("LikeHome total with service fee"), "$210.00");
  assert.equal(view.rows.get("Current base nightly average"), "$100.00");
  assert.equal(view.rows.get("Nights"), "2");
  assert.equal(view.rows.get("Provider listed stay total (reference)"), "$230.00");
  assert.equal(view.nodes.filter((node) => node.type === "dl").length, 1);
  assert.match(view.html, /text-lg font-semibold[^>]*>\$226\.80 USD/);
  assert.match(view.html, /sm:grid-cols-2/);
  assert.match(view.html, /internal demo payment step\. No card is charged/);
  assert.match(view.html, /The current price has changed since your search/);
  harness.render();
  assert.equal(calls, 0);
});

test("optional reference and zero fee/tax render truthfully without replacing the final authoritative amount", () => {
  const view = checkoutHarness({ ...quote, provider_total_with_taxes_fees: null,
    likehome_reservation_total: 200, likehome_payment_amount: 200 }).render();
  assert.equal(view.rows.has("Provider listed stay total (reference)"), false);
  assert.equal(view.rows.get("LikeHome service fee"), "$0.00");
  assert.equal(view.rows.get("Tax"), "$0.00");
  assert.equal(view.rows.get("Final booking total"), "$200.00 USD");
});

function session() {
  const entries = new Map();
  globalThis.window = { sessionStorage: {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: (key) => entries.delete(key),
  } };
  saveAccessToken("test-user-token");
}

test("displaying a validated quote adds no requests and reservation keeps accepted quote, guest, context and payment routing", async () => {
  session();
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ path: new URL(url).pathname, init });
    if (url.endsWith("/hotels/revalidate")) return new Response(JSON.stringify(quote));
    if (url.endsWith("/bookings/create")) return new Response(JSON.stringify({ user_id: 7, hotel_id: 8, room_type_id: 9, reservation_id: 10, payment_id: 11 }));
    throw new Error("Unexpected request");
  };
  const harness = checkoutHarness(await revalidateHotel(selection));
  harness.render();
  harness.render().reserve.props.onClick();
  await new Promise(setImmediate);
  assert.deepEqual(calls.map((call) => call.path), ["/hotels/revalidate", "/bookings/create"]);
  assert.deepEqual(JSON.parse(calls[1].init.body), {
    hotel_token: selection.property_token, ...guest, q: selection.q,
    check_in_date: selection.check_in_date, check_out_date: selection.check_out_date,
    adults: 2, children: 0, currency: "USD", gl: "us", hl: "en",
    price_per_night: 100, accepted_payment_amount: 226.80,
  });
  assert.equal(calls[1].init.headers.Authorization, "Bearer test-user-token");
  assert.deepEqual(harness.navigation, ["/payment/11"]);
});

test("HTTP 409 updates the disclosed breakdown from the new quote without automatically recreating the booking", async () => {
  session();
  const changedQuote = { ...quote, current_price_per_night: 100.50, provider_base_total: 201,
    likehome_reservation_total: 211.05, likehome_payment_amount: 227.93 };
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(new URL(url).pathname);
    return url.endsWith("/bookings/create") ? new Response("conflict", { status: 409 }) : new Response(JSON.stringify(changedQuote));
  };
  const harness = checkoutHarness(quote);
  harness.render().reserve.props.onClick();
  await new Promise(setImmediate);
  const view = harness.render();
  assert.equal(view.rows.get("Stay subtotal"), "$201.00");
  assert.equal(view.rows.get("LikeHome service fee"), "$10.05");
  assert.equal(view.rows.get("Tax"), "$16.88");
  assert.equal(view.rows.get("Final booking total"), "$227.93 USD");
  assert.match(view.html, /Review this current quote and confirm again/);
  assert.deepEqual(calls, ["/bookings/create", "/hotels/revalidate"]);
  assert.deepEqual(harness.navigation, []);
});
