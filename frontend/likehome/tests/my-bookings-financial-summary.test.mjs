import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { afterEach, beforeEach, test } from "node:test";
import { cloneElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

import { ApiError } from "../lib/api.ts";

const originalFetch = globalThis.fetch;
let unexpectedFetches;
beforeEach(() => {
  unexpectedFetches = 0;
  globalThis.fetch = async () => { unexpectedFetches++; throw new Error("Unexpected live fetch"); };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  assert.equal(unexpectedFetches, 0, "component tests must never reach fetch");
});
const require = createRequire(import.meta.url);
const tick = () => new Promise(setImmediate);

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function summary(id = 42) {
  return {
    reservation_id: id, reservation_revision: 0, reservation_status: "confirmed", currency: "USD",
    latest_change_id: null, current_reservation_total: 210, current_booking_obligation: 226.8,
    original_booking_payment: { payment_id: id + 100, reservation_id: id, amount: 226.8,
      payment_type: "booking", payment_status: "paid" },
    outstanding_booking_amount: 0, paid_additional_charges: 0, pending_additional_charges: 0,
    failed_additional_charges: 0, voided_additional_charges: 0, recorded_internal_credits: 0,
    outstanding_additional_amount: 0, adjustments: [], cancellation_reconciliations: [],
    reconciliation_credits: 0, reconciliation_debits: 0, cancellation_payment: null,
    outstanding_cancellation_amount: 0,
  };
}

function adjustment(kind = "charge", status = "paid", amount = 45.36) {
  return { adjustment_id: 1, change_id: 7, reservation_id: 42, currency: "USD", entry_role: "price_change",
    reconciles_adjustment_id: null, kind, status, amount,
    settled_at: status === "paid" ? "2026-10-15T12:00:00Z" : null };
}

function text(node) {
  if (Array.isArray(node)) return node.map(text).join("");
  if (node && typeof node === "object") return text(node.props?.children);
  return node === null || node === undefined || typeof node === "boolean" ? "" : String(node);
}

function loadComponent(path, imports) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  });
  const loaded = { exports: {} };
  new Function("require", "module", "exports", outputText)(
    (name) => {
      if (Object.hasOwn(imports, name)) return imports[name];
      if (name === "react/jsx-runtime") return require(name);
      throw new Error(`Unexpected component dependency: ${name}`);
    }, loaded, loaded.exports,
  );
  return loaded.exports.default;
}

// Matches the existing project's TSX/Node convention. Actual component handlers
// and effect callbacks run with a deterministic hook scheduler, then React renders
// the resulting host tree. This is not a DOM, React scheduling, or browser test.
function harness({ status = "authenticated", readSummary = async (id) => summary(id) } = {}) {
  const instances = new Map();
  const calls = [], navigation = [], writes = [];
  let current, pendingEffects, seen, disposed = false;
  const auth = { status, invalidateSession: () => { auth.status = "unauthenticated"; calls.push({ operation: "invalidate" }); } };
  const router = { replace: (href) => navigation.push(href) };
  const hooks = {
    useState(initial) {
      const instance = current, index = instance.cursor++;
      if (!(index in instance.slots)) instance.slots[index] = { value: typeof initial === "function" ? initial() : initial };
      const slot = instance.slots[index];
      return [slot.value, (value) => {
        writes.push({ mounted: instance.mounted });
        slot.value = typeof value === "function" ? value(slot.value) : value;
      }];
    },
    useRef(initial) {
      const index = current.cursor++;
      if (!(index in current.slots)) current.slots[index] = { value: { current: initial } };
      return current.slots[index].value;
    },
    useEffect(effect, dependencies) {
      const instance = current, index = instance.cursor++;
      if (!(index in instance.slots)) instance.slots[index] = {};
      const slot = instance.slots[index];
      if (!slot.dependencies || dependencies.some((value, i) => !Object.is(value, slot.dependencies[i]))) {
        pendingEffects.push(() => {
          slot.cleanup?.();
          slot.dependencies = dependencies;
          slot.cleanup = effect();
        });
      }
    },
  };
  // Only the read-only adapter is permitted. Any added booking, payment,
  // cancellation, confirmation or settlement call fails closed and is recorded.
  const readers = new Proxy({
    getReservationFinancialSummary: (id) => { calls.push({ operation: "summary", id }); return readSummary(id); },
  }, {
    get(target, name) {
      if (Object.hasOwn(target, name)) return target[name];
      return () => {
        calls.push({ operation: "UNEXPECTED", name });
        throw new Error(`Unexpected adapter: ${String(name)}`);
      };
    },
  });
  const Root = loadComponent("../components/BookingFinancialSummary.tsx", {
    react: hooks,
    "next/navigation": { useRouter: () => router },
    "@/components/AuthProvider": { useAuth: () => auth },
    "@/lib/api": { ApiError }, "@/lib/bookings": readers,
  });

  function unmount(instance) {
    instance.slots.forEach((slot) => slot.cleanup?.());
    instance.mounted = false;
  }
  function expand(node, path) {
    if (Array.isArray(node)) return node.map((child, i) => {
      const expanded = expand(child, `${path}/${child?.key ?? i}`);
      return expanded && typeof expanded === "object" && !Array.isArray(expanded)
        ? cloneElement(expanded, { key: child?.key ?? i }) : expanded;
    });
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") return renderComponent(node.type, node.props, `${path}/${node.type.name}/${node.key ?? ""}`);
    return cloneElement(node, { children: expand(node.props.children, `${path}/children`) });
  }
  function renderComponent(component, props, path) {
    seen.add(path);
    if (!instances.has(path)) instances.set(path, { slots: [], mounted: true });
    const previous = current;
    current = instances.get(path);
    current.cursor = 0;
    const result = component(props);
    current = previous;
    return expand(result, path);
  }
  return {
    calls, navigation, auth, writes,
    render(props = { reservationId: 42 }) {
      assert.equal(disposed, false);
      seen = new Set(); pendingEffects = [];
      const tree = renderComponent(Root, props, "root");
      for (const [path, instance] of instances) {
        if (!seen.has(path)) { unmount(instance); instances.delete(path); }
      }
      const nodes = [];
      function visit(node) {
        if (Array.isArray(node)) return node.forEach(visit);
        if (!node || typeof node !== "object") return;
        nodes.push(node); visit(node.props.children);
      }
      visit(tree);
      const rows = new Map();
      for (const node of nodes) {
        const children = node.props.children;
        if (node.type === "div" && Array.isArray(children) && children[0]?.type === "dt") {
          rows.set(text(children[0]), text(children[1]));
        }
      }
      const view = { html: renderToStaticMarkup(tree), nodes, rows,
        buttons: (label) => nodes.filter((n) => n.type === "button" && text(n) === label) };
      pendingEffects.forEach((effect) => effect());
      return view;
    },
    unmount() { instances.forEach(unmount); instances.clear(); disposed = true; },
  };
}

async function loaded(value) {
  const h = harness({ readSummary: async () => value });
  h.render(); await tick();
  return { h, view: h.render() };
}

test("paid unchanged booking renders independent USD totals, original payment and a calm empty history", async () => {
  const { h, view } = await loaded(summary());
  assert.equal(view.rows.get("Current reservation total (before tax)"), "$210.00");
  assert.equal(view.rows.get("Current booking obligation (including tax)"), "$226.80");
  assert.equal(view.rows.get("Original booking payment"), "$226.80 · paid");
  assert.equal(view.rows.has("Outstanding original booking amount"), false);
  assert.match(view.html, /No reservation changes have been recorded\./);
  assert.match(view.html, /No bank or payment processor charge or refund is made here/);
  assert.doesNotMatch(view.html, /Adjustment history|Cancellation accounting|\$436\.80|<table|Net balance/);
  assert.equal(view.nodes.filter((n) => n.type === "h4").length, 1);
  assert.equal(view.buttons("Retry financial summary").length, 0);
  h.render(); h.render();
  assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }]);
});

test("pending original payment displays its separate outstanding amount without adding a payment action", async () => {
  const value = summary();
  value.original_booking_payment.payment_status = "pending"; value.outstanding_booking_amount = 226.8;
  const { view } = await loaded(value);
  assert.equal(view.rows.get("Original booking payment"), "$226.80 · pending");
  assert.equal(view.rows.get("Outstanding original booking amount"), "$226.80");
  assert.equal(view.nodes.filter((n) => n.type === "button" || n.type === "a").length, 0);
});

test("paid, pending, failed, voided and credit categories remain separate with explicit history statuses", async (t) => {
  for (const [status, kind, label] of [
    ["paid", "charge", "Paid additional charges"], ["pending", "charge", "Pending additional charges"],
    ["failed", "charge", "Failed additional charges"], ["voided", "charge", "Voided additional charges"],
    ["recorded", "credit", "Recorded internal credits"],
  ]) {
    await t.test(label, async () => {
      const value = summary(); value.latest_change_id = 7; value.reservation_revision = 1;
      value.adjustments = [adjustment(kind, status)];
      value[kind === "credit" ? "recorded_internal_credits" : `${status}_additional_charges`] = 45.36;
      if (["pending", "failed"].includes(status)) value.outstanding_additional_amount = 45.36;
      const { view } = await loaded(value);
      assert.equal(view.rows.get(label), "$45.36");
      assert.match(view.html, new RegExp(`${kind === "credit" ? "Internal credit" : "Additional charge"} · <span[^>]*>${status}</span>`));
      assert.match(view.html, /not cash refunds, spendable balances, or reward points/);
      assert.match(view.html, /not deducted from the outstanding amounts/);
      assert.equal(view.rows.get("Current booking obligation (including tax)"), "$226.80");
      assert.equal(view.nodes.filter((n) => n.type === "li").length, 1);
    });
  }
});

test("internal credits do not reduce an outstanding additional charge", async () => {
  const value = summary(); value.latest_change_id = 8;
  value.adjustments = [adjustment("credit", "recorded", 45.36), { ...adjustment("charge", "pending", 90.72), adjustment_id: 2, change_id: 8 }];
  value.recorded_internal_credits = 45.36; value.pending_additional_charges = value.outstanding_additional_amount = 90.72;
  const { view } = await loaded(value);
  assert.equal(view.rows.get("Recorded internal credits"), "$45.36");
  assert.equal(view.rows.get("Outstanding additional amount"), "$90.72");
  assert.equal(view.rows.has("Net balance"), false);
});

test("cancelled booking renders cancellation payment, original status and both recorded reconciliation directions", async () => {
  const value = summary(); value.reservation_status = "cancelled"; value.latest_change_id = 8; value.reservation_revision = 5;
  value.original_booking_payment.payment_status = "refunded";
  value.cancellation_payment = { payment_id: 200, reservation_id: 42, amount: 33.6, payment_type: "cancellation", payment_status: "pending" };
  value.outstanding_cancellation_amount = 33.6;
  value.adjustments = [adjustment(), { ...adjustment("credit", "recorded", 10), adjustment_id: 2, change_id: 8 }];
  value.paid_additional_charges = value.reconciliation_credits = 45.36;
  value.recorded_internal_credits = value.reconciliation_debits = 10;
  value.cancellation_reconciliations = value.adjustments.map((entry, i) => ({ ...entry, adjustment_id: i + 3,
    entry_role: "cancellation_reconciliation", reconciles_adjustment_id: entry.adjustment_id,
    kind: entry.kind === "charge" ? "credit" : "charge", status: "recorded", settled_at: null }));
  const { view } = await loaded(value);
  assert.equal(view.rows.get("Original booking payment"), "$226.80 · refunded");
  assert.equal(view.rows.get("Separate cancellation payment"), "$33.60 · pending");
  assert.equal(view.rows.get("Outstanding cancellation amount"), "$33.60");
  assert.equal(view.rows.get("Recorded reconciliation credits"), "$45.36");
  assert.equal(view.rows.get("Recorded reconciliation debits"), "$10.00");
  assert.match(view.html, /Cancellation reconciliation history/);
  assert.match(view.html, /Reconciliation credit/); assert.match(view.html, /Reconciliation charge/);
  assert.match(view.html, /do not represent money paid or refunded/);
  assert.equal(view.nodes.filter((n) => n.type === "button" || n.type === "a").length, 0);
});

test("absent cancellation data and changes without monetary adjustments do not invent transactions", async () => {
  const value = summary(); value.latest_change_id = 7;
  let { view } = await loaded(value);
  assert.match(view.html, /No additional charges or credits were recorded/);
  assert.doesNotMatch(view.html, /No reservation changes|Cancellation accounting/);
  assert.equal(view.nodes.filter((n) => n.type === "li").length, 0);
  // Defensive presentation only: Checkpoint 5 rejects this incomplete cancelled
  // response, but optional data must never crash the view or turn into a fake fee.
  value.reservation_status = "cancelled";
  ({ view } = await loaded(value));
  assert.match(view.html, /No cancellation payment information is available/);
  assert.match(view.html, /No cancellation reconciliation entries have been recorded/);
  assert.equal(view.rows.has("Separate cancellation payment"), false);
  assert.equal(view.rows.has("Outstanding cancellation amount"), false);
});

test("unauthenticated and restoring components do not request or display summaries", () => {
  for (const status of ["restoring", "unauthenticated"]) {
    const h = harness({ status });
    assert.equal(h.render().html, ""); assert.equal(h.calls.length, 0);
  }
});

test("switching reservations hides old success immediately and ignores late success or 401", async () => {
  for (const lateFailure of [false, true]) {
    const first = deferred(), second = deferred();
    const h = harness({ readSummary: (id) => id === 42 ? first.promise : second.promise });
    h.render(); let view = h.render({ reservationId: 43 });
    assert.match(view.html, /Loading financial summary/);
    if (lateFailure) first.reject(new ApiError(401)); else first.resolve(summary(42));
    await tick(); view = h.render({ reservationId: 43 });
    assert.equal(h.navigation.length, 0); assert.equal(h.auth.status, "authenticated");
    assert.equal(view.rows.size, 0);
    const fresh = summary(43); fresh.current_booking_obligation = 999;
    second.resolve(fresh); await tick(); view = h.render({ reservationId: 43 });
    assert.equal(view.rows.get("Current booking obligation (including tax)"), "$999.00");
  }
  const h = harness(); h.render(); await tick(); h.render();
  assert.match(h.render({ reservationId: 43 }).html, /Loading financial summary/);
  assert.equal(h.calls.filter((c) => c.operation === "summary").length, 2);
});

test("markup uses wrapping, single-column mobile grids and touch-sized read-only retry controls", async () => {
  const value = summary(); value.current_booking_obligation = 199999999.98;
  const { view } = await loaded(value);
  assert.match(view.html, /\$199,999,999\.98/);
  assert.match(view.html, /min-w-0/); assert.match(view.html, /break-words/);
  assert.match(view.html, /sm:grid-cols-2/);
  assert.doesNotMatch(view.html, /<table|min-w-\[|w-\[[0-9]|overflow-x/);
  const h = harness({ readSummary: async () => { throw new ApiError(500); } });
  h.render(); await tick();
  const retry = h.render().buttons("Retry financial summary")[0];
  assert.match(retry.props.className, /min-h-11/); assert.equal(retry.props.type, "button");
});

test("module loading has no read or fetch side effects; only an authenticated mount starts a read", async () => {
  const pending = deferred();
  const h = harness({ readSummary: () => pending.promise });
  assert.deepEqual(h.calls, []);
  assert.deepEqual(h.writes, []);
  let view = h.render();
  assert.match(view.html, /aria-label="Reservation financial summary"/);
  assert.match(view.html, /role="status"[^>]*>Loading financial summary/);
  assert.equal(view.rows.size, 0);
  assert.equal(view.nodes.filter((n) => n.type === "a" || n.type === "button").length, 0);
  h.render(); h.render();
  assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }]);
  pending.resolve(summary()); await tick(); view = h.render();
  assert.equal(view.rows.get("Current booking obligation (including tax)"), "$226.80");
  assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }]);
});

test("HTTP failures use safe status or alert messages without an automatic retry", async (t) => {
  for (const status of [400, 404, 409, 422, 500, 502, 503, 504]) {
    await t.test(String(status), async () => {
      const h = harness({ readSummary: async () => { throw new ApiError(status); } });
      h.render(); await tick(); let view = h.render();
      assert.doesNotMatch(view.html, /API request failed|stack|token/);
      assert.deepEqual(h.navigation, []);
      assert.equal(h.auth.status, "authenticated");
      if (status === 404) {
        assert.match(view.html, /role="status"[^>]*>This financial summary is unavailable/);
        assert.equal(view.buttons("Retry financial summary").length, 0);
      } else {
        assert.match(view.html, /role="alert"/);
        assert.equal(view.buttons("Retry financial summary").length, 1);
      }
      await tick(); view = h.render(); h.render();
      assert.equal(view.rows.size, 0);
      assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }]);
      h.unmount();
    });
  }
});

test("network, JSON and adapter-validation failures hide raw details and retain explicit retry", async (t) => {
  for (const [label, error] of [
    ["network", new TypeError("synthetic-secret failed to fetch")],
    ["JSON", new SyntaxError("synthetic-secret invalid JSON")],
    ["malformed success", new Error("Financial summary returned an unexpected response synthetic-secret")],
  ]) {
    await t.test(label, async () => {
      // The real adapter rejects malformed payloads before the component sees them.
      const h = harness({ readSummary: async () => { throw error; } });
      h.render(); await tick(); const view = h.render();
      assert.match(view.html, /role="alert"/);
      assert.match(view.html, /We could not load this financial summary. Please try again./);
      assert.doesNotMatch(view.html, /synthetic-secret|TypeError|SyntaxError|unexpected response|invalid JSON/);
      assert.equal(view.buttons("Retry financial summary").length, 1);
      assert.equal(view.rows.size, 0);
      assert.deepEqual(h.navigation, []);
      assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }]);
      h.unmount();
    });
  }
});

test("explicit retry reads only the same summary and suppresses same-tick duplicate starts", async () => {
  const retry = deferred(); let attempts = 0;
  const h = harness({ readSummary: () => ++attempts === 1 ? Promise.reject(new ApiError(500)) : retry.promise });
  h.render(); await tick();
  const button = h.render().buttons("Retry financial summary")[0];
  button.props.onClick(); button.props.onClick();
  let view = h.render();
  assert.match(view.html, /Loading financial summary/);
  assert.equal(view.buttons("Retry financial summary").length, 0);
  h.render();
  assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }, { operation: "summary", id: 42 }]);
  retry.resolve(summary()); await tick(); view = h.render();
  assert.equal(view.rows.get("Current booking obligation (including tax)"), "$226.80");
  assert.equal(view.nodes.filter((n) => n.type === "a" || n.type === "button").length, 0);
});

test("a failed explicit retry waits for another customer action", async () => {
  const h = harness({ readSummary: async () => { throw new ApiError(500); } });
  h.render(); await tick();
  h.render().buttons("Retry financial summary")[0].props.onClick();
  h.render(); await tick();
  assert.equal(h.render().buttons("Retry financial summary").length, 1);
  await tick(); h.render(); h.render();
  assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }, { operation: "summary", id: 42 }]);
});

test("active 401 invalidates once, redirects to login and removes financial content", async () => {
  const h = harness({ readSummary: async () => { throw new ApiError(401); } });
  h.render(); await tick();
  assert.equal(h.render().html, "");
  assert.equal(h.auth.status, "unauthenticated");
  assert.deepEqual(h.navigation, ["/login"]);
  assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }, { operation: "invalidate" }]);
  await tick(); h.render();
  assert.equal(h.navigation.length, 1);
});

test("authentication restoration starts the read only after authentication and logout hides success", async () => {
  const h = harness({ status: "restoring" });
  assert.equal(h.render().html, ""); assert.deepEqual(h.calls, []);
  h.auth.status = "authenticated";
  assert.match(h.render().html, /Loading financial summary/);
  await tick(); assert.match(h.render().html, /\$226\.80/);
  h.auth.status = "unauthenticated";
  assert.equal(h.render().html, "");
  assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }]);
});

test("logout suppresses pending success and pending 401 without redirecting an inactive session", async (t) => {
  for (const lateFailure of [false, true]) {
    await t.test(lateFailure ? "late 401" : "late success", async () => {
      const pending = deferred(); const h = harness({ readSummary: () => pending.promise });
      h.render(); h.auth.status = "unauthenticated";
      assert.equal(h.render().html, ""); const writes = h.writes.length;
      if (lateFailure) pending.reject(new ApiError(401)); else pending.resolve(summary());
      await tick();
      assert.equal(h.render().html, "");
      assert.equal(h.writes.length, writes);
      assert.deepEqual(h.navigation, []);
      assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }]);
      h.unmount();
    });
  }
});

test("unmount ignores late success and all errors without state writes, navigation or further requests", async (t) => {
  for (const [label, error] of [["success", null], ["401", new ApiError(401)], ["404", new ApiError(404)],
    ["network", new Error("synthetic-secret")]]) {
    await t.test(label, async () => {
      const pending = deferred(); const h = harness({ readSummary: () => pending.promise });
      h.render(); h.unmount(); const writes = h.writes.length;
      if (error) pending.reject(error); else pending.resolve(summary());
      await tick();
      assert.equal(h.writes.length, writes);
      assert.deepEqual(h.navigation, []);
      assert.equal(h.auth.status, "authenticated");
      assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }]);
    });
  }
});

test("a fresh mount reads independently after the prior instance was unmounted", async () => {
  const pending = deferred(); const old = harness({ readSummary: () => pending.promise });
  old.render(); old.unmount();
  const fresh = harness(); fresh.render(); await tick();
  assert.match(fresh.render().html, /\$226\.80/);
  pending.reject(new ApiError(401)); await tick();
  assert.deepEqual(old.navigation, []);
  assert.deepEqual(fresh.calls, [{ operation: "summary", id: 42 }]);
  assert.equal(fresh.auth.status, "authenticated");
});

test("an optional authoritative reader supplies initial data and retry without calling the default adapter", async () => {
  let reads = 0; const ids = [];
  const readSummary = async (id) => {
    ids.push(id);
    if (++reads === 1) throw new ApiError(500);
    const value = summary(id); value.reservation_revision = 9; return value;
  };
  const h = harness(); const props = { reservationId: 42, readSummary };
  h.render(props); await tick();
  h.render(props).buttons("Retry financial summary")[0].props.onClick();
  h.render(props); await tick();
  assert.match(h.render(props).html, /Summary revision 9/);
  assert.deepEqual(ids, [42, 42]);
  assert.deepEqual(h.calls, []);
});

test("rendering and retries never log, persist or expose credentials, raw payloads or financial mutation controls", async () => {
  const descriptors = new Map(); const persisted = [], logged = [], reads = [];
  const secret = "synthetic-secret-bearer-token";
  const storage = { getItem: (key) => { reads.push(key); return secret; },
    setItem: (...args) => persisted.push(args), removeItem: (...args) => persisted.push(args),
    clear: () => persisted.push(["clear"]) };
  const originalConsole = new Map(["log", "warn", "error", "info", "debug"].map((key) => [key, console[key]]));
  try {
    for (const [key, value] of Object.entries({ window: { localStorage: storage, sessionStorage: storage },
      localStorage: storage, sessionStorage: storage, document: { set cookie(value) { persisted.push(value); } } })) {
      descriptors.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
      Object.defineProperty(globalThis, key, { configurable: true, value });
    }
    for (const key of originalConsole.keys()) console[key] = (...args) => logged.push(args);
    let attempts = 0;
    const h = harness({ readSummary: async () => {
      if (++attempts === 1) throw new Error(`raw backend payload ${secret}`);
      return summary();
    } });
    h.auth.token = secret;
    h.render(); await tick(); let view = h.render();
    assert.doesNotMatch(view.html, /synthetic-secret|raw backend payload/);
    view.buttons("Retry financial summary")[0].props.onClick();
    h.render(); await tick(); view = h.render();
    assert.doesNotMatch(view.html, /synthetic-secret|raw backend payload|<form|<input|<a\b|<button\b/);
    assert.deepEqual(h.calls, [{ operation: "summary", id: 42 }, { operation: "summary", id: 42 }]);
    assert.deepEqual(persisted, []); assert.deepEqual(logged, []); assert.deepEqual(reads, []);
    h.unmount();
  } finally {
    for (const [key, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
    for (const [key, value] of originalConsole) console[key] = value;
  }
});
