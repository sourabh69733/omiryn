// Home page motion. One main animation per section:
// hero orbit, chat demo, venn, reasons marquee, card stack.
// Everything renders in a readable final state when the user prefers reduced motion.
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = window.matchMedia("(pointer: fine)").matches;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ─────────── Avatars: small drawn faces, no stock photos ─────────── */
const AVATARS = [
  { bg: "#ede9fe", skin: "#f2c9a5", hair: "#2b1b12", shirt: "#7c3aed", style: 0 },
  { bg: "#fef3c7", skin: "#c68a5e", hair: "#111827", shirt: "#f59e0b", style: 3 },
  { bg: "#d1fae5", skin: "#e0ac80", hair: "#5b3a21", shirt: "#10b981", style: 1 },
  { bg: "#fce7f3", skin: "#e8b48f", hair: "#1f1410", shirt: "#db2777", style: 1 },
  { bg: "#e0f2fe", skin: "#8d5a3b", hair: "#0f0f10", shirt: "#0ea5e9", style: 2 },
  { bg: "#ffe4e6", skin: "#f6d5bd", hair: "#a0522d", shirt: "#f43f5e", style: 0 },
  { bg: "#ecfccb", skin: "#d49a6a", hair: "#2b1b12", shirt: "#65a30d", style: 2 },
  { bg: "#f3e8ff", skin: "#b9784f", hair: "#1a1a1a", shirt: "#9333ea", style: 3 },
];

function avatarSvg(i) {
  const a = AVATARS[i % AVATARS.length];
  const back = a.style === 1
    ? `<path d="M17 36c0-11 6-18 15-18s15 7 15 18v14c-3-2-4-5-4-9H21c0 4-1 7-4 9z" fill="${a.hair}"/>`
    : "";
  const top = [
    `<path d="M18 35c0-10 6-17 14-17s14 7 14 17c-3-5-8-8-14-8s-11 3-14 8z" fill="${a.hair}"/>`,
    `<path d="M18 34c1-10 7-16 14-16s13 6 14 16c-5-4-9-6-14-6-6 0-10 2-14 6z" fill="${a.hair}"/>`,
    `<circle cx="32" cy="15" r="6" fill="${a.hair}"/><path d="M18 35c0-10 6-16 14-16s14 6 14 16c-4-6-9-8-14-8s-10 2-14 8z" fill="${a.hair}"/>`,
    `<g fill="${a.hair}"><circle cx="22" cy="26" r="6"/><circle cx="29" cy="21" r="6.5"/><circle cx="37" cy="21" r="6.5"/><circle cx="43" cy="27" r="6"/><circle cx="20" cy="33" r="4.5"/><circle cx="45" cy="34" r="4.5"/></g>`,
  ][a.style];
  return `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <rect width="64" height="64" fill="${a.bg}"/>
    ${back}
    <path d="M12 66c2-11 10-17 20-17s18 6 20 17z" fill="${a.shirt}"/>
    <rect x="28" y="44" width="8" height="7" rx="3" fill="${a.skin}"/>
    <circle cx="32" cy="36" r="13.5" fill="${a.skin}"/>
    ${top}
    <circle cx="27" cy="37" r="1.6" fill="#1f2937"/><circle cx="37" cy="37" r="1.6" fill="#1f2937"/>
    <path d="M27.5 42.5q4.5 3.5 9 0" stroke="#1f2937" stroke-width="1.6" fill="none" stroke-linecap="round"/>
    <circle cx="24" cy="41" r="2" fill="#f472b6" opacity=".35"/><circle cx="40" cy="41" r="2" fill="#f472b6" opacity=".35"/>
  </svg>`;
}

function paintAvatars(root = document) {
  $$("[data-avatar]", root).forEach((el) => {
    el.innerHTML = avatarSvg(Number(el.dataset.avatar));
  });
}
paintAvatars();

/* ─────────── Nav ─────────── */
const nav = $("#nav-main");
const onScroll = () => nav.classList.toggle("is-scrolled", window.scrollY > 24);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

$$('a[href^="#"]').forEach((link) => {
  link.addEventListener("click", (event) => {
    const href = link.getAttribute("href");
    if (href === "#") return;
    const target = $(href);
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  });
});

/* ─────────── Marquee of "matched because" ─────────── */
const REASONS = [
  "both hate small talk",
  "same 2am overthinking",
  "chai over coffee, always",
  "different teams, same banter",
  "both laugh at bad puns",
  "night owls",
  "side quests every weekend",
  "disagree on pineapple pizza, still vibe",
  "same taste in bad movies",
  "both believe in second chances",
];
$$(".o-marquee-row").forEach((row, rowIndex) => {
  const list = rowIndex ? [...REASONS].reverse() : REASONS;
  const chips = list
    .map((text, i) => `<span class="o-chip-m"><span class="pair"><span data-avatar="${i}"></span><span data-avatar="${i + 3}"></span></span><small>matched because</small> ${text}</span>`)
    .join("");
  // Two copies so the CSS loop is seamless.
  row.innerHTML = `<div class="o-marquee-track">${chips}</div><div class="o-marquee-track" aria-hidden="true">${chips}</div>`;
  paintAvatars(row);
});

/* ─────────── Card stack ─────────── */
const MATCHES = [
  { a: 3, name: "Riya", reasons: ["You both laugh at terrible puns", "Both think weekends are for side quests"], starter: "Best bad movie ever?" },
  { a: 1, name: "Arjun", reasons: ["Same 2am overthinking", "Different on cricket vs football, both find it funny"], starter: "Your 2am rabbit hole" },
  { a: 4, name: "Sana", reasons: ["Both hate small talk", "Both believe in second chances"], starter: "A take you'll defend forever" },
  { a: 7, name: "Dev", reasons: ["Chai loyalists", "Both want to build something of your own"], starter: "Dream side project?" },
];
const stack = $("#o-stack");
stack.innerHTML = MATCHES.map((m) => `
  <article class="o-card">
    <div class="o-card-top">
      <div class="pair"><span data-avatar="0"></span><span data-avatar="${m.a}"></span></div>
      <div><small>New match</small><strong>You &amp; ${m.name}</strong></div>
    </div>
    <p class="o-card-label">You matched because</p>
    <ul>${m.reasons.map((r) => `<li>${r}</li>`).join("")}</ul>
    <p class="o-card-label">Start with</p>
    <span class="o-card-starter">${m.starter}</span>
    <span class="o-card-cta">Say hi</span>
  </article>`).join("");
paintAvatars(stack);

const cards = () => $$(".o-card", stack);
function layoutStack(animate = true) {
  cards().forEach((card, i) => {
    const props = {
      x: 0,
      y: i * 14,
      rotation: [0, -4, 4, -2][i] ?? 0,
      scale: 1 - i * 0.05,
      zIndex: 10 - i,
      opacity: i > 3 ? 0 : 1,
    };
    card.setAttribute("aria-hidden", i === 0 ? "false" : "true");
    animate && !reduce ? gsap.to(card, { ...props, duration: 0.5, ease: "back.out(1.6)" }) : gsap.set(card, props);
  });
}
function sendTopToBack(direction = 1) {
  const top = cards()[0];
  if (!top) return;
  const finish = () => {
    stack.appendChild(top);
    layoutStack();
  };
  if (reduce) return finish();
  gsap.to(top, {
    x: direction * 420,
    rotation: direction * 22,
    opacity: 0,
    duration: 0.4,
    ease: "power2.in",
    onComplete: finish,
  });
}
layoutStack(false);
$("#o-stack-next").addEventListener("click", () => sendTopToBack(1));

// Pointer drag on the top card: flick past the threshold to send it back.
let drag = null;
stack.addEventListener("pointerdown", (event) => {
  const top = cards()[0];
  if (!top || !top.contains(event.target)) return;
  drag = { card: top, startX: event.clientX, startY: event.clientY };
  top.setPointerCapture(event.pointerId);
  top.classList.add("is-dragging");
});
stack.addEventListener("pointermove", (event) => {
  if (!drag) return;
  const dx = event.clientX - drag.startX;
  const dy = event.clientY - drag.startY;
  gsap.set(drag.card, { x: dx, y: dy * 0.3, rotation: dx / 14 });
});
const endDrag = (event) => {
  if (!drag) return;
  const dx = event.clientX - drag.startX;
  drag.card.classList.remove("is-dragging");
  if (Math.abs(dx) > 90) sendTopToBack(Math.sign(dx));
  else layoutStack();
  drag = null;
};
stack.addEventListener("pointerup", endDrag);
stack.addEventListener("pointercancel", endDrag);

/* ─────────── Hero orbit ─────────── */
// Rings of people rotate around you. Every few seconds one lights up,
// a line draws from you to them, and a short reason appears.
const ORBIT_REASONS = [
  "same chaotic humor",
  "both overthink at 2am",
  "different views, zero drama",
  "same taste in bad movies",
  "both hate small talk",
  "chai loyalists",
];
const RINGS = [
  { r: 0.2, count: 4, size: 64, speed: 60, dir: 1 },
  { r: 0.34, count: 6, size: 56, speed: 90, dir: -1 },
  { r: 0.48, count: 8, size: 46, speed: 120, dir: 1 },
];
const orbit = $("#o-orbit");
const orbitPeople = [];

function buildOrbit() {
  $$(".o-ring", orbit).forEach((el) => el.remove());
  orbitPeople.length = 0;
  const size = orbit.offsetWidth;
  let avatarIndex = 1;
  RINGS.forEach((ring, ringIndex) => {
    const el = document.createElement("div");
    el.className = `o-ring ring-${ringIndex}`;
    const radius = ring.r * size;
    el.style.setProperty("--d", `${radius * 2}px`);
    for (let i = 0; i < ring.count; i += 1) {
      const angle = (360 / ring.count) * i + ringIndex * 17;
      const line = document.createElement("span");
      line.className = "o-link";
      line.style.width = `${radius}px`;
      line.style.transform = `rotate(${angle}deg)`;
      const person = document.createElement("div");
      person.className = "o-person";
      person.style.setProperty("--s", `${ring.size}px`);
      const rad = (angle * Math.PI) / 180;
      person.style.left = `calc(50% + ${Math.cos(rad) * radius}px)`;
      person.style.top = `calc(50% + ${Math.sin(rad) * radius}px)`;
      person.innerHTML = `<span class="o-face" data-avatar="${avatarIndex % 8 || 1}"></span><span class="o-tip"></span>`;
      avatarIndex += 1;
      el.append(line, person);
      orbitPeople.push({ person, line, ring: el });
    }
    orbit.appendChild(el);
    el.dataset.speed = ring.speed;
    el.dataset.dir = ring.dir;
  });
  paintAvatars(orbit);
}
buildOrbit();

let orbitTimer = null;
function spinOrbit() {
  $$(".o-ring", orbit).forEach((ring) => {
    const dir = Number(ring.dataset.dir);
    const faces = $$(".o-person", ring);
    gsap.to(ring, { rotation: 360 * dir, duration: Number(ring.dataset.speed), repeat: -1, ease: "none" });
    // Keep faces upright while the ring turns.
    gsap.to(faces, { rotation: -360 * dir, duration: Number(ring.dataset.speed), repeat: -1, ease: "none" });
  });
}
let lastPick = -1;
function pickMatch() {
  // Pick someone clearly inside the visible spotlight.
  const box = $(".o-orbit-wrap").getBoundingClientRect();
  const visible = orbitPeople
    .map((p, i) => ({ ...p, i, rect: p.person.getBoundingClientRect() }))
    .filter(({ rect, i }) => {
      const x = (rect.left + rect.width / 2 - box.left) / box.width;
      const y = (rect.top + rect.height / 2 - box.top) / box.height;
      return i !== lastPick && x > 0.25 && x < 0.75 && y > 0.18 && y < 0.62;
    });
  if (!visible.length) return;
  const pick = visible[Math.floor(Math.random() * visible.length)];
  lastPick = pick.i;
  const tip = $(".o-tip", pick.person);
  tip.textContent = ORBIT_REASONS[Math.floor(Math.random() * ORBIT_REASONS.length)];
  pick.person.classList.add("is-match");
  gsap.timeline({ onComplete: () => pick.person.classList.remove("is-match") })
    .fromTo(pick.line, { scaleX: 0, autoAlpha: 1 }, { scaleX: 1, duration: 0.6, ease: "power2.out" })
    .fromTo(tip, { autoAlpha: 0, y: 8, scale: 0.9 }, { autoAlpha: 1, y: 0, scale: 1, duration: 0.4, ease: "back.out(2)" }, 0.3)
    .fromTo(".o-you", { scale: 1 }, { scale: 1.08, duration: 0.25, yoyo: true, repeat: 1, ease: "power2.out" }, 0.5)
    .to([pick.line, tip], { autoAlpha: 0, duration: 0.4 }, 2.4);
}

const progress = $$("#o-progress li");
function setStep(index) {
  progress.forEach((li, i) => {
    li.classList.toggle("is-on", i <= index);
    li.classList.toggle("is-now", i === index);
  });
}

const SCRIPT = [
  { who: "bot", text: "Hey! What's something you'll defend forever?" },
  { who: "me", text: "Chai beats coffee. [Always.]", tag: "Chai loyalist" },
  { who: "bot", text: "Respect. What made you laugh this week?" },
  { who: "me", text: "My friend's [2am voice notes] 😂", tag: "Night owl" },
  { who: "bot", text: "Haha. And what can you not stand?" },
  { who: "me", text: "[Small talk.] Just say the real thing.", tag: "No small talk" },
];
const feed = $("#o-feed");
const slots = $("#o-vibe-slots");
const matchPop = $("#o-matchpop");

function bubble(step) {
  const el = document.createElement("div");
  el.className = `o-msg ${step.who}`;
  el.innerHTML = step.text.replace(/\[(.+?)\]/g, "<mark>$1</mark>");
  return el;
}
function typing() {
  const el = document.createElement("div");
  el.className = "o-msg bot o-typing";
  el.innerHTML = "<i></i><i></i><i></i>";
  return el;
}
function addTag(text) {
  const tag = document.createElement("span");
  tag.className = `o-vtag c${slots.children.length + 1}`;
  tag.textContent = text;
  slots.appendChild(tag);
  return tag;
}

function renderStaticDemo() {
  SCRIPT.forEach((step) => {
    feed.appendChild(bubble(step));
    if (step.tag) addTag(step.tag);
  });
  matchPop.classList.add("is-static");
}

function playDemo() {
  const tl = gsap.timeline({ onComplete: () => gsap.delayedCall(0.2, resetDemo) });

  tl.call(() => setStep(0));
  SCRIPT.forEach((step) => {
    if (step.who === "bot") {
      const dots = typing();
      tl.call(() => { feed.appendChild(dots); scrollFeed(); });
      tl.fromTo(dots, { autoAlpha: 0, y: 8 }, { autoAlpha: 1, y: 0, duration: 0.25 });
      tl.to({}, { duration: 0.45 });
      tl.call(() => dots.remove());
    }
    const msg = bubble(step);
    tl.call(() => { feed.appendChild(msg); scrollFeed(); });
    tl.fromTo(msg, { autoAlpha: 0, y: 14, scale: 0.94 }, {
      autoAlpha: 1, y: 0, scale: 1, duration: 0.45, ease: "back.out(1.8)",
      transformOrigin: step.who === "me" ? "100% 100%" : "0% 100%",
    });
    if (step.tag) {
      // The highlighted words glow, then a tag flies from them into "Your vibe".
      tl.call(() => {
        setStep(1);
        const mark = $("mark", msg);
        mark.classList.add("is-on");
        const tag = addTag(step.tag);
        const from = mark.getBoundingClientRect();
        const to = tag.getBoundingClientRect();
        gsap.fromTo(tag,
          { x: from.left - to.left, y: from.top - to.top, scale: 0.6, autoAlpha: 0 },
          { x: 0, y: 0, scale: 1, autoAlpha: 1, duration: 0.6, ease: "expo.out", delay: 0.25 });
      });
      tl.to({}, { duration: 0.7 });
    } else {
      tl.to({}, { duration: 0.3 });
    }
  });

  tl.call(() => { $(".o-phone").classList.add("is-thinking"); setStep(2); });
  tl.to({}, { duration: 0.3 });
  tl.fromTo(matchPop, { autoAlpha: 0, y: 40, scale: 0.8, rotation: -6 }, {
    autoAlpha: 1, y: 0, scale: 1, rotation: -4, duration: 0.8, ease: "elastic.out(1, 0.6)",
  });
  tl.from($$(".o-matchpop-faces > span", matchPop), { scale: 0, stagger: 0.08, duration: 0.4, ease: "back.out(3)" }, "<0.2");
  tl.to({}, { duration: 3.2 });
  tl.to([feed, slots, matchPop], { autoAlpha: 0, duration: 0.4 });
  return tl;
}
function scrollFeed() {
  gsap.to(feed, { scrollTop: feed.scrollHeight, duration: 0.4, ease: "power2.out" });
}
function resetDemo() {
  setStep(-1);
  feed.innerHTML = "";
  slots.innerHTML = "";
  $(".o-phone").classList.remove("is-thinking");
  gsap.set([feed, slots], { autoAlpha: 1 });
  gsap.set(matchPop, { autoAlpha: 0 });
  demo = playDemo();
}

/* ─────────── Start ─────────── */
let demo = null;
const demoStage = $(".o-demo");
if (reduce) {
  renderStaticDemo();
  setStep(2);
} else {
  gsap.set(matchPop, { autoAlpha: 0 });
  // The chat starts when its section is on screen, then loops.
  ScrollTrigger.create({ trigger: demoStage, start: "top 75%", once: true, onEnter: () => { demo = playDemo(); } });
  document.addEventListener("visibilitychange", () => {
    if (!demo) return;
    document.hidden ? demo.pause() : demo.resume();
  });
}

if (!reduce) {
  // Hero intro: words rise, then subtext and button, then the orbit fades in.
  gsap.timeline({ defaults: { ease: "expo.out" } })
    .from(".o-h1 .w > span", { yPercent: 110, duration: 0.9, stagger: 0.07 })
    .from("[data-intro]", { y: 20, autoAlpha: 0, duration: 0.8, stagger: 0.1 }, "-=0.6")
    .from(".o-you", { scale: 0, duration: 0.9, ease: "back.out(2)" }, 0.3)
    .from(".o-person", { scale: 0, autoAlpha: 0, duration: 0.6, stagger: { each: 0.03, from: "random" }, ease: "back.out(2)" }, 0.5);
  spinOrbit();
  gsap.delayedCall(1.8, pickMatch);
  orbitTimer = setInterval(() => { if (!document.hidden) pickMatch(); }, 2800);

  // Background blobs drift.
  $$(".o-blob").forEach((blob, i) => {
    gsap.to(blob, {
      x: () => gsap.utils.random(-120, 120),
      y: () => gsap.utils.random(-80, 80),
      duration: 9 + i * 2,
      repeat: -1,
      yoyo: true,
      repeatRefresh: true,
      ease: "sine.inOut",
    });
  });

  // Section reveals.
  gsap.set("[data-rv]", { y: 50, autoAlpha: 0 });
  ScrollTrigger.batch("[data-rv]", {
    start: "top 88%",
    once: true,
    onEnter: (batch) => gsap.to(batch, { y: 0, autoAlpha: 1, duration: 1, stagger: 0.12, ease: "expo.out" }),
  });

  // Venn: circles slide together as you scroll, shared traits pop in the middle.
  gsap.timeline({ scrollTrigger: { trigger: ".venn", start: "top 85%", end: "center 55%", scrub: 0.8 } })
    .fromTo(".venn-a", { xPercent: -35, rotation: -8 }, { xPercent: 0, rotation: 0 }, 0)
    .fromTo(".venn-b", { xPercent: 35, rotation: 8 }, { xPercent: 0, rotation: 0 }, 0)
    .fromTo(".venn-mid span", { scale: 0, autoAlpha: 0 }, { scale: 1, autoAlpha: 1, stagger: 0.1 }, 0.4)
    .fromTo(".venn-note", { autoAlpha: 0, y: 20 }, { autoAlpha: 1, y: 0 }, 0.7);

  // Card stack deals in.
  gsap.from(".o-card", {
    scrollTrigger: { trigger: "#o-stack", start: "top 80%", once: true },
    y: 120, rotation: () => gsap.utils.random(-25, 25), autoAlpha: 0, stagger: 0.1, duration: 0.9, ease: "back.out(1.4)",
    onComplete: () => layoutStack(),
  });

  // Big final headline scales up with scroll.
  gsap.fromTo(".o-final-title", { scale: 0.85 }, { scale: 1, scrollTrigger: { trigger: ".o-final", start: "top bottom", end: "center center", scrub: true } });

  if (finePointer) {
    // Soft glow follows the cursor.
    const glow = $(".o-cursor");
    const gx = gsap.quickTo(glow, "x", { duration: 0.6, ease: "power3" });
    const gy = gsap.quickTo(glow, "y", { duration: 0.6, ease: "power3" });
    window.addEventListener("pointermove", (e) => { gx(e.clientX); gy(e.clientY); glow.classList.add("on"); });

    // Magnetic buttons.
    $$(".magnetic").forEach((btn) => {
      const mx = gsap.quickTo(btn, "x", { duration: 0.4, ease: "power3" });
      const my = gsap.quickTo(btn, "y", { duration: 0.4, ease: "power3" });
      btn.addEventListener("pointermove", (e) => {
        const r = btn.getBoundingClientRect();
        mx((e.clientX - r.left - r.width / 2) * 0.25);
        my((e.clientY - r.top - r.height / 2) * 0.35);
      });
      btn.addEventListener("pointerleave", () => { mx(0); my(0); });
    });

    // The orbit leans toward the cursor a little.
    const wrap = $(".o-orbit-wrap");
    const ox = gsap.quickTo(orbit, "x", { duration: 1, ease: "power3" });
    const oy = gsap.quickTo(orbit, "y", { duration: 1, ease: "power3" });
    $("#hero").addEventListener("pointermove", (e) => {
      const r = wrap.getBoundingClientRect();
      ox(((e.clientX - r.left) / r.width - 0.5) * 30);
      oy(((e.clientY - r.top) / r.height - 0.5) * 16);
    });
  }
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    gsap.killTweensOf($$(".o-ring, .o-person", orbit));
    buildOrbit();
    if (!reduce) spinOrbit();
  }, 250);
});
