const HARD_REJECTION_SCORE = 0;

export function scoreMatch(userA, userB) {
  const hardFilter = evaluateHardFilters(userA, userB);

  if (!hardFilter.pass) {
    return {
      score: HARD_REJECTION_SCORE,
      decision: "reject",
      explanation: hardFilter.reason,
      breakdown: {
        hardFilters: 0
      }
    };
  }

  const breakdown = {
    intent: scoreRelationshipIntent(userA.relationshipIntent, userB.relationshipIntent, 20),
    values: scoreOverlap(userA.values, userB.values, 25),
    lifestyle: scoreOverlap(userA.lifestyle, userB.lifestyle, 15),
    communication: scoreExact(userA.communicationStyle, userB.communicationStyle, 15),
    family: scoreFamilyExpectations(userA, userB, 15),
    location: scoreLocation(userA, userB, 10)
  };

  const score = roundScore(Object.values(breakdown).reduce((total, value) => total + value, 0));

  return {
    score,
    decision: score >= 70 ? "strong_candidate" : score >= 50 ? "possible_candidate" : "low_priority",
    explanation: explainScore(score, breakdown, userA, userB),
    breakdown
  };
}

export function evaluateHardFilters(userA, userB) {
  if (userA.id === userB.id) {
    return { pass: false, reason: "Users cannot be matched with themselves." };
  }

  const ageCheckA = isAgeInPreference(userB.age, userA.agePreference);
  const ageCheckB = isAgeInPreference(userA.age, userB.agePreference);

  if (!ageCheckA || !ageCheckB) {
    return { pass: false, reason: "Age preference does not match both users." };
  }

  if (hasDealbreakerConflict(userA, userB) || hasDealbreakerConflict(userB, userA)) {
    return { pass: false, reason: "At least one hard dealbreaker is triggered." };
  }

  if (!isRelationshipIntentCompatible(userA.relationshipIntent, userB.relationshipIntent)) {
    return { pass: false, reason: "Relationship intent is not compatible." };
  }

  return { pass: true };
}

function isAgeInPreference(age, preference = {}) {
  if (typeof age !== "number") return false;
  if (typeof preference.min === "number" && age < preference.min) return false;
  if (typeof preference.max === "number" && age > preference.max) return false;
  return true;
}

function hasDealbreakerConflict(user, candidate) {
  return (user.dealbreakers || []).some((dealbreaker) => {
    if (dealbreaker.severity !== "hard") return false;
    return candidate.attributes?.includes(dealbreaker.type);
  });
}

function isRelationshipIntentCompatible(intentA, intentB) {
  if (!intentA || !intentB) return false;
  if (intentA === intentB) return true;
  const serious = new Set(["long_term", "marriage"]);
  return serious.has(intentA) && serious.has(intentB);
}

function scoreExact(valueA, valueB, maxScore) {
  if (!valueA || !valueB) return 0;
  if (valueA === valueB) return maxScore;
  return 0;
}

function scoreRelationshipIntent(intentA, intentB, maxScore) {
  if (!intentA || !intentB) return 0;
  if (intentA === intentB) return maxScore;
  return isRelationshipIntentCompatible(intentA, intentB) ? maxScore * 0.8 : 0;
}

function scoreOverlap(listA = [], listB = [], maxScore) {
  if (!listA.length || !listB.length) return 0;
  const setB = new Set(listB);
  const overlapCount = listA.filter((item) => setB.has(item)).length;
  const denominator = Math.max(listA.length, listB.length);
  return roundScore((overlapCount / denominator) * maxScore);
}

function scoreFamilyExpectations(userA, userB, maxScore) {
  const fields = ["religionImportance", "familyInvolvement", "childrenPreference"];
  const matches = fields.filter((field) => userA[field] && userA[field] === userB[field]).length;
  return roundScore((matches / fields.length) * maxScore);
}

function scoreLocation(userA, userB, maxScore) {
  if (!userA.city || !userB.city) return 0;
  if (userA.city === userB.city) return maxScore;
  if (userA.openToRelocation || userB.openToRelocation) return maxScore / 2;
  return 0;
}

function explainScore(score, breakdown, userA, userB) {
  const strengths = Object.entries(breakdown)
    .filter(([, value]) => value > 0)
    .map(([key]) => key);

  const friction = [];

  if (userA.city !== userB.city) friction.push("location");
  if (userA.communicationStyle !== userB.communicationStyle) friction.push("communication style");
  if (userA.childrenPreference !== userB.childrenPreference) friction.push("children preference");

  return [
    `Compatibility score is ${score}.`,
    strengths.length ? `Strong areas: ${strengths.join(", ")}.` : "No strong compatibility signals found yet.",
    friction.length ? `Possible friction: ${friction.join(", ")}.` : "No major friction found in the current profile data."
  ].join(" ");
}

function roundScore(value) {
  return Math.round(value * 100) / 100;
}
