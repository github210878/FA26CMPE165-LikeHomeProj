import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("../components/LoadingSkeletons.tsx", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
});
const loadedModule = { exports: {} };
new Function("require", "module", "exports", outputText)(require, loadedModule, loadedModule.exports);
const skeletons = loadedModule.exports;

test("named loading skeletons announce status and hide decorative blocks", () => {
  for (const [component, label] of [
    [skeletons.PageLoadingSkeleton, "Loading page"],
    [skeletons.SessionLoadingSkeleton, "Checking your session"],
    [skeletons.SearchResultsSkeleton, "Searching for stays"],
    [skeletons.BookingListSkeleton, "Loading your bookings"],
    [skeletons.BookingDetailsSkeleton, "Loading booking details"],
    [skeletons.CheckoutSkeleton, "Checking the current stay rate"],
    [skeletons.PaymentSkeleton, "Loading payment"],
  ]) {
    const markup = renderToStaticMarkup(component({}));
    assert.match(markup, new RegExp(`role="status" aria-label="${label}" aria-busy="true"`));
    assert.match(markup, /animate-pulse/);
    assert.match(markup, /aria-hidden="true"/);
  }
});