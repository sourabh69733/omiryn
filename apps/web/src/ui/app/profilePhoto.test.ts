import assert from "node:assert/strict";
import test from "node:test";
import { mainPhoto } from "./profilePhoto";

test("the first uploaded photo in any slot wins", () => {
  assert.equal(mainPhoto({ profile_photo_urls: ["", "b.jpg", "c.jpg"] }, "google.jpg"), "b.jpg");
});

test("falls back to the old single photo, then the sign-in photo", () => {
  assert.equal(mainPhoto({ profile_photo_url: "old.jpg" }, "google.jpg"), "old.jpg");
  assert.equal(mainPhoto({ profile_photo_urls: [] }, "google.jpg"), "google.jpg");
  assert.equal(mainPhoto(null), null);
});
