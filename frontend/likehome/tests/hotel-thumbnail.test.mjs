import assert from "node:assert/strict";
import test from "node:test";

import { getHotelThumbnailUrl } from "../lib/hotel-thumbnail.ts";

test("accepts absolute HTTP(S) hotel thumbnails", () => {
  assert.equal(
    getHotelThumbnailUrl("  https://images.example.com/hotel.jpg  "),
    "https://images.example.com/hotel.jpg",
  );
  assert.equal(
    getHotelThumbnailUrl("http://images.example.com/hotel.jpg"),
    "http://images.example.com/hotel.jpg",
  );
});

test("missing, relative, and unsafe thumbnail values use the card fallback", () => {
  for (const value of [null, undefined, "", "  ", "/hotel.jpg", "not a URL", "data:image/png;base64,abc", "javascript:alert(1)", 42]) {
    assert.equal(getHotelThumbnailUrl(value), null);
  }
});
