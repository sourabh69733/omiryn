import assert from "node:assert/strict";
import test from "node:test";
import { ratingsByMessage, withRating } from "./replyRatings";

test("the newest rating of a message wins and old bad ratings stay bad", () => {
  const ratings = ratingsByMessage([
    { message_index: 3, rating: "good" },
    { message_index: 3, rating: "bad" },
    { message_index: 5, rating: "harmful" },
  ]);
  assert.equal(ratings.get(3), "good");
  assert.equal(ratings.get(5), "bad");
});

test("a rating can be set, changed and removed", () => {
  const rated = withRating(new Map(), 1, "good");
  assert.equal(withRating(rated, 1, "bad").get(1), "bad");
  assert.equal(withRating(rated, 1, null).has(1), false);
  assert.equal(rated.get(1), "good");
});
