// The soft "vibe fingerprint" ring around a profile photo, the same blob language as the landing hero.
// Shapes come from a seed (the user's id), so each person's ring is their own and never changes on reload.

function seededRandom(seed: string): () => number {
  let state = 2166136261;
  for (const char of seed) state = Math.imul(state ^ char.charCodeAt(0), 16777619);
  return () => {
    state = Math.imul(state ^ (state >>> 15), 2246822507);
    state = Math.imul(state ^ (state >>> 13), 3266489909);
    state ^= state >>> 16;
    return (state >>> 0) / 4294967296;
  };
}

// A smooth closed blob around (center, center): radius varies by up to `wobble` of itself.
export function blobPath(seed: string, center: number, radius: number, wobble = 0.12, points = 7): string {
  const random = seededRandom(seed);
  const corners = Array.from({ length: points }, (_, index) => {
    const angle = (index / points) * Math.PI * 2;
    const r = radius * (1 - wobble + random() * wobble * 2);
    return [center + Math.cos(angle) * r, center + Math.sin(angle) * r];
  });
  // Catmull-Rom through the corners, written as cubic Beziers.
  const at = (index: number) => corners[(index + points) % points];
  let path = `M${at(0)[0].toFixed(1)} ${at(0)[1].toFixed(1)}`;
  for (let index = 0; index < points; index += 1) {
    const [p0, p1, p2, p3] = [at(index - 1), at(index), at(index + 1), at(index + 2)];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    path += ` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return `${path} Z`;
}
