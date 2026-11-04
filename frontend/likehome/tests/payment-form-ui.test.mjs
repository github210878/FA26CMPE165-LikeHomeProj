import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { test } from "node:test";
import { createRequire } from "node:module";
import ts from "typescript";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("../components/PaymentForm.tsx", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
});
const loadedModule = { exports: {} };
const Link = ({ href, children, ...props }) => createElement("a", { href, ...props }, children);
new Function("require", "module", "exports", outputText)((name) => {
  if (name === "next/link") return { __esModule: true, default: Link };
  return require(name);
}, loadedModule, loadedModule.exports);

const PaymentForm = loadedModule.exports.default;
const pendingPayment = {
  payment_id: 17,
  reservation_id: 42,
  amount: 374.22,
  payment_type: "booking",
  payment_status: "pending",
};

function render(payment, overrides = {}) {
  return renderToStaticMarkup(createElement(PaymentForm, {
    payment,
    submitting: false,
    paymentError: "",
    onSubmit: () => {},
    onRefresh: () => {},
    ...overrides,
  }));
}

test("pending payment shows a demo confirmation form without collecting card details", () => {
  const html = render(pendingPayment);

  assert.match(html, /<form/);
  assert.match(html, /LikeHome demo payment/);
  assert.match(html, /No card details are collected/);
  assert.match(html, /type="checkbox"/);
  assert.match(html, /Confirm demo payment/);
  assert.match(html, /disabled=""/);
  assert.doesNotMatch(html, /card number|cvv|credit card/i);
});

test("payment errors explain recovery and prevent another submit until status is refreshed", () => {
  const html = render(pendingPayment, {
    paymentError: "Payment was not confirmed. Refresh its status before retrying.",
  });

  assert.match(html, /role="alert"/);
  assert.match(html, /Payment was not confirmed/);
  assert.match(html, /Refresh payment status/);
  assert.match(html, /disabled=""/);
});

test("paid payment shows success feedback and a booking confirmation link", () => {
  const html = render({ ...pendingPayment, payment_status: "paid" });

  assert.match(html, /Payment recorded successfully/);
  assert.match(html, /href="\/booking-confirmation\/42"/);
  assert.match(html, /View confirmation/);
  assert.doesNotMatch(html, /<form/);
});