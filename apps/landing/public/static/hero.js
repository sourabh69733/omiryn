// Hero strands: two streams of conversation (teal from him, coral from her) flow toward a
// point between them and gather into a warm gold spark. Canvas only, no dependencies.
(function () {
  const stage = document.querySelector(".hx-stage");
  if (!stage) return;
  const canvas = stage.querySelector(".hx-strands");
  const man = stage.querySelector(".hx-man");
  const woman = stage.querySelector(".hx-woman");
  const ctx = canvas.getContext("2d");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const TEAL = [111, 181, 176];
  const CORAL = [227, 154, 133];
  const GOLD = [217, 178, 111];
  const INTRO_DELAY = 1.2; // seconds, lets the boot loader finish
  const INTRO_LENGTH = 2.8;

  let width = 0;
  let height = 0;
  let strands = [];
  let dust = [];
  let meet = { x: 0, y: 0 };
  let energy = 0;
  let frameId = 0;
  let startedAt = 0;
  let lastTime = 0;

  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  const rand = (min, max) => min + Math.random() * (max - min);

  function bezier(s, t) {
    const u = 1 - t;
    return {
      x: u * u * u * s.p0.x + 3 * u * u * t * s.p1.x + 3 * u * t * t * s.p2.x + t * t * t * s.p3.x,
      y: u * u * u * s.p0.y + 3 * u * u * t * s.p1.y + 3 * u * t * t * s.p2.y + t * t * t * s.p3.y,
    };
  }

  // First part (0..t) of a cubic curve, as four control points.
  function bezierHead(s, t) {
    const mix = (a, b) => ({ x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t) });
    const a = mix(s.p0, s.p1);
    const b = mix(s.p1, s.p2);
    const c = mix(s.p2, s.p3);
    const d = mix(a, b);
    const e = mix(b, c);
    return [s.p0, a, d, mix(d, e)];
  }

  function build(originMan, originWoman) {
    const perSide = width < 700 ? 34 : 64;
    strands = [];
    [[originMan, TEAL, 1], [originWoman, CORAL, -1]].forEach(([origin, color, dir]) => {
      for (let i = 0; i < perSide; i++) {
        const p0 = { x: origin.x + rand(-0.03, 0.03) * width, y: origin.y + rand(-0.09, 0.09) * height };
        const p3 = { x: meet.x + rand(-16, 16), y: meet.y + rand(-12, 12) };
        const span = p3.x - p0.x;
        strands.push({
          p0,
          p1: { x: p0.x + span * 0.35, y: p0.y + rand(-0.2, 0.2) * height },
          p2: { x: p0.x + span * 0.72, y: p3.y + rand(-0.14, 0.14) * height },
          p3,
          color,
          dir,
          width: rand(0.5, 1.1),
          alpha: rand(0.1, 0.26),
          speed: rand(0.05, 0.12),
          phase: Math.random(),
          node: Math.random() < 0.12,
          prev: 0,
        });
      }
    });
    dust = Array.from({ length: 46 }, () => ({
      angle: Math.random() * Math.PI * 2,
      radius: rand(4, 70),
      speed: rand(-0.4, 0.4),
      size: rand(0.6, 1.5),
    }));
  }

  function layout() {
    const box = stage.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = box.width;
    height = box.height;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const m = man.getBoundingClientRect();
    const w = woman.getBoundingClientRect();
    meet = { x: width * 0.5, y: height * 0.74 };
    build(
      { x: m.left - box.left + m.width * 0.5, y: m.top - box.top + m.height * 0.42 },
      { x: w.left - box.left + w.width * 0.5, y: w.top - box.top + w.height * 0.4 }
    );
  }

  function drawFrame(time, dt, intro, still) {
    ctx.clearRect(0, 0, width, height);
    ctx.globalCompositeOperation = "lighter";
    energy = Math.min(energy * Math.exp(-dt * 1.1), 1.8);

    // Glow where the two streams meet.
    const glow = 46 + energy * 70;
    const g = ctx.createRadialGradient(meet.x, meet.y, 0, meet.x, meet.y, glow * 2.4);
    g.addColorStop(0, rgba(GOLD, 0.2 + energy * 0.28));
    g.addColorStop(0.35, rgba(GOLD, 0.07 + energy * 0.08));
    g.addColorStop(1, rgba(GOLD, 0));
    ctx.fillStyle = g;
    ctx.fillRect(meet.x - glow * 2.4, meet.y - glow * 2.4, glow * 4.8, glow * 4.8);

    strands.forEach((s) => {
      // Faint path, drawn in from the face toward the middle.
      const head = bezierHead(s, Math.max(intro, 0.001));
      ctx.beginPath();
      ctx.moveTo(head[0].x, head[0].y);
      ctx.bezierCurveTo(head[1].x, head[1].y, head[2].x, head[2].y, head[3].x, head[3].y);
      ctx.strokeStyle = rgba(s.color, s.alpha);
      ctx.lineWidth = s.width;
      ctx.stroke();

      // Moving light along the path.
      const t = still ? s.phase : (s.phase + time * s.speed) % 1;
      if (!still && t < s.prev && intro >= 1) energy += 0.045; // arrived at the spark
      s.prev = t;
      if (t > intro) return;
      const p = bezier(s, t);
      const tail = bezier(s, Math.max(t - 0.035, 0));
      const fade = Math.sin(Math.PI * t);
      ctx.beginPath();
      ctx.moveTo(tail.x, tail.y);
      ctx.lineTo(p.x, p.y);
      ctx.strokeStyle = rgba(s.color, 0.55 * fade);
      ctx.lineWidth = s.width + 0.4;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(p.x, p.y, 1 + fade * 0.9, 0, Math.PI * 2);
      ctx.fillStyle = rgba(s.color, 0.9 * fade);
      ctx.fill();

      // A few strands carry a shared-signal node that pulses gold.
      if (s.node && intro >= 1) {
        const n = bezier(s, 0.78);
        const pulse = 0.5 + 0.5 * Math.sin(time * 1.3 + s.phase * 6);
        ctx.beginPath();
        ctx.arc(n.x, n.y, 1.6 + pulse * 1.4, 0, Math.PI * 2);
        ctx.fillStyle = rgba(GOLD, 0.35 + pulse * 0.45);
        ctx.fill();
      }
    });

    // Dust around the spark, drawn tighter as more light arrives.
    dust.forEach((d) => {
      if (!still) d.angle += d.speed * dt;
      const r = d.radius * (0.6 + energy * 0.5);
      ctx.beginPath();
      ctx.arc(meet.x + Math.cos(d.angle) * r, meet.y + Math.sin(d.angle) * r * 0.7, d.size, 0, Math.PI * 2);
      ctx.fillStyle = rgba(GOLD, 0.25 + Math.min(energy, 1) * 0.5);
      ctx.fill();
    });
    ctx.globalCompositeOperation = "source-over";
  }

  function tick(now) {
    const time = (now - startedAt) / 1000;
    const dt = Math.min((now - lastTime) / 1000 || 0.016, 0.05);
    lastTime = now;
    const intro = ease(Math.min(Math.max((time - INTRO_DELAY) / INTRO_LENGTH, 0), 1));
    drawFrame(time, dt, intro, false);
    frameId = requestAnimationFrame(tick);
  }

  function start() {
    if (frameId || reduceMotion.matches) return;
    startedAt = startedAt || performance.now();
    lastTime = performance.now();
    frameId = requestAnimationFrame(tick);
  }
  function stop() {
    cancelAnimationFrame(frameId);
    frameId = 0;
  }

  function init() {
    layout();
    if (reduceMotion.matches) {
      energy = 0.9;
      drawFrame(0, 0, 1, true);
    } else {
      start();
    }
  }

  // Only animate while the hero is on screen and the tab is visible.
  new IntersectionObserver(([entry]) => (entry.isIntersecting ? start() : stop())).observe(stage);
  document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));

  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      layout();
      if (reduceMotion.matches) drawFrame(0, 0, 1, true);
    }, 150);
  });

  // Wait for the portraits so strand origins sit on the faces.
  const ready = [man, woman].map((img) => (img.complete ? Promise.resolve() : new Promise((r) => img.addEventListener("load", r, { once: true }))));
  Promise.all(ready).then(init);
})();
