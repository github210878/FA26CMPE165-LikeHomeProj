import assert from "node:assert/strict";
import test from "node:test";
import { getLocalToday, validateSearchInputs } from "../lib/search-validation.mjs";

const TODAY = "2026-09-29";
const VALID = { checkIn: "2026-10-02", checkOut: "2026-10-05", guests: "2" };
const validate = (overrides = {}) => validateSearchInputs({ ...VALID, ...overrides }, TODAY);

test("valid search inputs are accepted", () => {
  assert.deepEqual(validate(), {});
});

test("missing dates report both errors", () => {
  const errors = validate({ checkIn: "", checkOut: "" });
  assert.match(errors.checkIn, /Choose a check-in/);
  assert.match(errors.checkOut, /Choose a check-out/);
});

for (const value of ["2026-2-01", "2026-13-01", "2026-04-31", "2027-02-29", "0000-01-01", "2026-10-02T12:00:00"]) {
  test(`invalid calendar date ${value} is rejected`, () => {
    assert.match(validate({ checkIn: value }).checkIn, /valid check-in date/);
    assert.match(validate({ checkOut: value }).checkOut, /valid check-out date/);
  });
}

test("valid leap day is accepted", () => {
  assert.deepEqual(validate({ checkIn: "2028-02-29", checkOut: "2028-03-01" }), {});
});

test("past check-in is rejected but today is accepted", () => {
  assert.match(validate({ checkIn: "2026-09-28" }).checkIn, /cannot be in the past/);
  assert.deepEqual(validate({ checkIn: TODAY, checkOut: "2026-09-30" }), {});
});

for (const checkOut of ["2026-10-02", "2026-10-01"]) {
  test(`checkout ${checkOut} must be later than check-in`, () => {
    assert.match(validate({ checkOut }).checkOut, /must be after check-in/);
  });
}

for (const guests of ["", " ", "0", "-1", "21", "1.5", "1e1", "abc"]) {
  test(`invalid guest count ${JSON.stringify(guests)} is rejected`, () => {
    assert.ok(validate({ guests }).guests);
  });
}

for (const guests of ["1", "20", " 2 "]) {
  test(`valid guest count ${JSON.stringify(guests)} is accepted`, () => {
    assert.deepEqual(validate({ guests }), {});
  });
}

test("today uses local calendar fields rather than a UTC date conversion", () => {
  assert.equal(getLocalToday(new Date(2026, 8, 29, 23, 59)), TODAY);
});
