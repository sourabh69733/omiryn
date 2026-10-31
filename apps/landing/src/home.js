// Home page motion. One main animation per section:
// the photo shelf and its thread in the hero, the conversation set big in "How it works",
// the match card stack in the ink section.
// Everything renders in a readable final state when the user prefers reduced motion.
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = window.matchMedia("(pointer: fine)").matches;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ─────────── People: portrait photos (illustrative, not real users) ─────────── */
const PEOPLE = 10;
const photo = (i) => `/static/assets/people/p${(i % PEOPLE) + 1}.webp`;

function paintAvatars(root = document) {
  $$("[data-avatar]", root).forEach((el) => {
    el.innerHTML = `<img src="${photo(Number(el.dataset.avatar))}" alt="" loading="lazy" decoding="async">`;
  });
}
paintAvatars();

/* ─────────── Nav ─────────── */
const nav = $("#nav-main");
const onScroll = () => nav.classList.toggle("is-scrolled", window.scrollY > 24);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

// One "Start talking" at a time: the nav button shows only when the page's own buttons are off screen.
const pageCtas = $$('[data-track="hero_start_talking"], #cta [data-app-link]');
const ctaInView = new Set();
const ctaWatch = new IntersectionObserver((entries) => {
  entries.forEach((entry) => (entry.isIntersecting ? ctaInView.add(entry.target) : ctaInView.delete(entry.target)));
  nav.classList.toggle("show-cta", ctaInView.size === 0);
});
pageCtas.forEach((cta) => ctaWatch.observe(cta));

$$('a[href^="#"]').forEach((link) => {
  link.addEventListener("click", (event) => {
    const href = link.getAttribute("href");
    if (href === "#") return;
    const target = $(href);
    if (!target) return;
    event.preventDefault();
    flushBelowFold();
    target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  });
});

/* ─────────── Hero: the shelf of photos and the thread between two of them ─────────── */
const shelf = $("#o-shelf");
const threadPath = $("#o-thread-path");
const threadLabel = $("#o-thread-label");
const THREAD_PAIR = [1, 3];
const visibleCards = () => $$(".o-polaroid", shelf).filter((card) => card.offsetParent !== null);

// A curve from one photo to the other, in the shelf's own coordinates, with the label at its middle.
function drawThread() {
  const cards = visibleCards();
  const a = cards[THREAD_PAIR[0]];
  const b = cards[THREAD_PAIR[1]] ?? cards[cards.length - 1];
  if (!a || !b || a === b) return;
  const box = shelf.getBoundingClientRect();
  const center = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2 - box.left, y: r.top + r.height * 0.38 - box.top };
  };
  const p = center(a);
  const q = center(b);
  const lift = Math.min(90, Math.abs(q.x - p.x) * 0.35);
  const c1 = { x: p.x + (q.x - p.x) * 0.3, y: Math.min(p.y, q.y) - lift };
  const c2 = { x: p.x + (q.x - p.x) * 0.7, y: Math.min(p.y, q.y) - lift };
  threadPath.setAttribute("d", `M ${p.x} ${p.y} C ${c1.x} ${c1.y}, ${c2.x} ${c2.y}, ${q.x} ${q.y}`);
  threadPath.style.strokeDasharray = threadPath.getTotalLength();
  if (reduce || threadDrawn) threadPath.style.strokeDashoffset = 0;
  // Bezier midpoint (t = 0.5).
  const mid = { x: (p.x + 3 * c1.x + 3 * c2.x + q.x) / 8, y: (p.y + 3 * c1.y + 3 * c2.y + q.y) / 8 };
  threadLabel.style.left = `${mid.x}px`;
  threadLabel.style.top = `${mid.y}px`;
}
let threadDrawn = reduce;
window.addEventListener("resize", drawThread);

function heroIntro() {
  const cards = $$(".o-polaroid", shelf);
  const tl = gsap.timeline({ defaults: { ease: "expo.out" } });
  tl.from(".o-h1 .w > span", { yPercent: 110, duration: 0.9, stagger: 0.06 })
    .from("[data-intro]", { y: 16, autoAlpha: 0, duration: 0.7 }, "-=0.55")
    // Photos land on the table one by one.
    .from(cards, {
      y: 90,
      autoAlpha: 0,
      rotation: (i) => [-18, 14, -10, 16, -14, 10][i],
      duration: 0.9,
      stagger: 0.07,
      ease: "back.out(1.3)",
      clearProps: "transform,opacity,visibility",
    }, "-=0.6")
    // The thread ties two of them together, then the label pops.
    .call(() => { threadDrawn = true; drawThread(); }, null, "-=0.2")
    .fromTo(threadPath, { strokeDashoffset: () => threadPath.getTotalLength() }, { strokeDashoffset: 0, duration: 0.9, ease: "power2.inOut" })
    .fromTo(threadLabel, { autoAlpha: 0, scale: 0.6 }, { autoAlpha: 1, scale: 1, duration: 0.45, ease: "back.out(2)" }, "-=0.25");

  // Then they breathe: each photo drifts a little, forever.
  tl.call(() => {
    cards.forEach((card, i) => {
      gsap.to(card, { y: i % 2 ? 7 : -7, duration: 2.6 + i * 0.3, repeat: -1, yoyo: true, ease: "sine.inOut" });
    });
  });
  return tl;
}

/* ─────────── How it works: the conversation ─────────── */
// Omi asks, you answer, a phrase lights up and gets stamped as part of your vibe; after three,
// a match lands. Every element is in the DOM from the start (hidden, keeping its space), so the
// section never changes height while the loop runs.
const demo = $("#o-demo");
const bots = $$("[data-bot]", demo);
const mes = $$("[data-me]", demo);
const chips = $$("[data-chip]", demo);
const marks = $$("mark", demo);
const matchPop = $("#o-matchpop");
let demoLoop = null;
let demoVisible = false;

// The loop runs only while the conversation is on screen; it resumes where it left off.
new IntersectionObserver(([entry]) => {
  demoVisible = entry.isIntersecting;
  if (reduce) return;
  if (!demoLoop && demoVisible) demoCycle();
  else if (demoLoop) demoVisible ? demoLoop.resume() : demoLoop.pause();
}, { threshold: 0.35 }).observe(demo);

function demoReset() {
  bots.forEach((bot) => bot.classList.add("is-typing"));
  marks.forEach((mark) => mark.classList.remove("is-on"));
  gsap.set([...bots, ...mes], { autoAlpha: 0, y: 10 });
  gsap.set(chips, { autoAlpha: 0, scale: 1.8 });
  gsap.set(matchPop, { autoAlpha: 0, y: 24 });
}

function demoFinal() {
  bots.forEach((bot) => bot.classList.remove("is-typing"));
  marks.forEach((mark) => mark.classList.add("is-on"));
  gsap.set([...bots, ...mes, ...chips, matchPop], { autoAlpha: 1, y: 0, scale: 1 });
}

function demoCycle() {
  demoLoop = gsap.timeline({ paused: !demoVisible, defaults: { ease: "power2.out" }, onComplete: demoCycle });
  demoLoop.call(demoReset);
  bots.forEach((bot, i) => {
    demoLoop
      // Omi types, then the words replace the dots.
      .fromTo(bot, { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.3 }, "+=0.2")
      .to({}, { duration: 0.8 })
      .call(() => bot.classList.remove("is-typing"))
      .to({}, { duration: 1.0 })
      // You answer.
      .fromTo(mes[i], { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.3 })
      .to({}, { duration: 0.45 })
      // The phrase lights up and gets stamped.
      .call(() => marks[i].classList.add("is-on"))
      .fromTo(chips[i], { autoAlpha: 0, scale: 1.8 }, { autoAlpha: 1, scale: 1, duration: 0.35, ease: "power3.in" }, "+=0.3");
  });
  demoLoop
    // Someone who fits.
    .fromTo(matchPop, { autoAlpha: 0, y: 24 }, { autoAlpha: 1, y: 0, duration: 0.6, ease: "back.out(1.6)" }, "+=0.9")
    .to({}, { duration: 4.5 })
    // Fade out, then start over with a fresh chat.
    .to([...bots, ...mes, ...chips, matchPop], { autoAlpha: 0, duration: 0.4, ease: "power1.in" })
    .to({}, { duration: 0.5 });
  return demoLoop;
}

/* ─────────── Card stack ─────────── */
const MATCHES = [
  { a: 3, name: "Riya", reasons: ["You both laugh at terrible puns", "Both think weekends are for side quests"], starter: "Best bad movie ever?" },
  { a: 1, name: "Arjun", reasons: ["Same 2am overthinking", "Different on cricket vs football, both find it funny"], starter: "Your 2am rabbit hole" },
  { a: 4, name: "Sana", reasons: ["Both hate small talk", "Both believe in second chances"], starter: "A take you'll defend forever" },
  { a: 7, name: "Dev", reasons: ["Chai loyalists", "Both want to build something of your own"], starter: "Dream side project?" },
];
const stack = $("#o-stack");
function renderCards() {
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
}

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

function setupCards() {
  renderCards();
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
}

/* ─────────── Start ─────────── */
// Hero runs now. Everything below the fold is set up in small steps once the
// browser is idle, or right away on the first scroll or anchor click. The
// motion is the same, it just stops competing with the first paint.
const belowFold = [
  setupCards,
  () => !reduce && setupScrollMotion(),
  () => ScrollTrigger.refresh(),
];
const idle = window.requestIdleCallback ?? ((fn) => setTimeout(fn, 200));

function runNextStep() {
  belowFold.shift()?.();
  if (belowFold.length) idle(runNextStep, { timeout: 1000 });
}
function flushBelowFold() {
  while (belowFold.length) belowFold.shift()();
}
["scroll", "wheel", "touchmove", "keydown"].forEach((type) =>
  window.addEventListener(type, flushBelowFold, { once: true, passive: true })
);
// Opened on a #section link or mid-page (reload, back): set up everything now.
if (location.hash || window.scrollY > 0) flushBelowFold();
else window.addEventListener("load", () => idle(runNextStep, { timeout: 1000 }), { once: true });

if (reduce) {
  drawThread();
  demoFinal();
} else {
  demoReset();
  heroIntro();
}
// The thread depends on the photos' final layout; redraw once fonts and images settle.
document.fonts?.ready.then(drawThread);
window.addEventListener("load", drawThread, { once: true });

// Below-the-fold scroll motion, set up from the queue above.
function setupScrollMotion() {
  // Section reveals.
  gsap.set("[data-rv]", { y: 40, autoAlpha: 0 });
  ScrollTrigger.batch("[data-rv]", {
    start: "top 88%",
    once: true,
    onEnter: (batch) => gsap.to(batch, { y: 0, autoAlpha: 1, duration: 1, stagger: 0.12, ease: "expo.out" }),
  });

  // Card stack deals in.
  gsap.from(".o-card", {
    scrollTrigger: { trigger: "#o-stack", start: "top 80%", once: true },
    y: 120, rotation: () => gsap.utils.random(-25, 25), autoAlpha: 0, stagger: 0.1, duration: 0.9, ease: "back.out(1.4)",
    onComplete: () => layoutStack(),
  });

  // Big final headline scales up with scroll.
  gsap.fromTo(".o-final-title", { scale: 0.85 }, { scale: 1, scrollTrigger: { trigger: ".o-final", start: "top bottom", end: "center center", scrub: true } });
}

if (!reduce && finePointer) {
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

  // The shelf leans toward the cursor a little, each photo by a different amount.
  const layers = $$(".o-polaroid", shelf).map((card, i) => ({
    x: gsap.quickTo(card, "x", { duration: 1.1, ease: "power3" }),
    depth: 6 + (i % 3) * 5,
  }));
  $("#hero").addEventListener("pointermove", (e) => {
    const t = e.clientX / window.innerWidth - 0.5;
    layers.forEach((layer) => layer.x(-t * layer.depth * 2));
  });
}
