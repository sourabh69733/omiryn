// Home page motion. One main animation per section:
// a live chat with Omi in the hero, step reveals, the match card stack in the dark section.
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

/* ─────────── Hero: a live chat with Omi ─────────── */
// The conversation is the hero: Omi asks, you answer, a phrase lights up and sticks to the side
// as part of your vibe; after three, a match lands. Every element is in the DOM from the start
// (hidden, keeping its space), so the stage never changes size while the loop runs.
const demo = $("#o-demo");
const bots = $$("[data-bot]", demo);
const mes = $$("[data-me]", demo);
const chips = $$("[data-chip]", demo);
const marks = $$("mark", demo);
const matchPop = $("#o-matchpop");
let demoLoop = null;
let heroVisible = true;

// Pause the loop while the hero is off screen; it resumes where it left off.
new IntersectionObserver(([entry]) => {
  heroVisible = entry.isIntersecting;
  if (demoLoop) heroVisible ? demoLoop.resume() : demoLoop.pause();
}).observe($("#hero"));

function demoReset() {
  bots.forEach((bot) => bot.classList.add("is-typing"));
  marks.forEach((mark) => mark.classList.remove("is-on"));
  gsap.set([...bots, ...mes, ...chips], { autoAlpha: 0, y: 10, scale: 1 });
  gsap.set(matchPop, { autoAlpha: 0, y: 24, scale: 0.9 });
  demo.classList.remove("is-thinking");
}

function demoFinal() {
  bots.forEach((bot) => bot.classList.remove("is-typing"));
  marks.forEach((mark) => mark.classList.add("is-on"));
  gsap.set([...bots, ...mes, ...chips, matchPop], { autoAlpha: 1, y: 0, scale: 1 });
  demo.classList.add("is-thinking");
}

function demoCycle() {
  demoLoop = gsap.timeline({ paused: !heroVisible, defaults: { ease: "power2.out" }, onComplete: demoCycle });
  demoLoop.call(demoReset);
  bots.forEach((bot, i) => {
    demoLoop
      // Omi types, then the words replace the dots.
      .fromTo(bot, { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.3 }, "+=0.2")
      .to({}, { duration: 0.9 })
      .call(() => bot.classList.remove("is-typing"))
      .to({}, { duration: 1.1 })
      // You answer.
      .fromTo(mes[i], { autoAlpha: 0, y: 10 }, { autoAlpha: 1, y: 0, duration: 0.3 })
      .to({}, { duration: 0.5 })
      // The phrase lights up and lands in your vibe.
      .call(() => marks[i].classList.add("is-on"))
      .fromTo(chips[i], { autoAlpha: 0, scale: 0.5, y: 14 }, { autoAlpha: 1, scale: 1, y: 0, duration: 0.5, ease: "back.out(2.2)" }, "+=0.35");
  });
  demoLoop
    // Someone who fits.
    .call(() => demo.classList.add("is-thinking"), null, "+=0.6")
    .fromTo(matchPop, { autoAlpha: 0, y: 24, scale: 0.9 }, { autoAlpha: 1, y: 0, scale: 1, duration: 0.6, ease: "back.out(1.6)" }, "+=0.5")
    .to({}, { duration: 4 })
    // Fade out, then start over with a fresh chat.
    .to([...bots, ...mes, ...chips, matchPop], { autoAlpha: 0, duration: 0.4, ease: "power1.in" })
    .to({}, { duration: 0.4 });
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
if (reduce) demoFinal();

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

if (!reduce) {
  demoReset();
  // Hero intro: the line rises, then the button; the conversation starts right after.
  gsap.timeline({ defaults: { ease: "expo.out" } })
    .from(".o-h1 .w > span", { yPercent: 110, duration: 0.8, stagger: 0.05 })
    .from("[data-intro]", { y: 16, autoAlpha: 0, duration: 0.7 }, "-=0.5")
    .add(demoCycle, 0.7);

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
}

// Below-the-fold scroll motion, set up from the queue above.
function setupScrollMotion() {
  // Section reveals.
  gsap.set("[data-rv]", { y: 50, autoAlpha: 0 });
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

  // The stickers and the match card lean toward the cursor a little.
  const lean = [$(".o-stickers"), matchPop];
  const lx = gsap.quickTo(lean, "x", { duration: 1.2, ease: "power3" });
  const ly = gsap.quickTo(lean, "y", { duration: 1.2, ease: "power3" });
  $("#hero").addEventListener("pointermove", (e) => {
    lx((e.clientX / window.innerWidth - 0.5) * 14);
    ly((e.clientY / window.innerHeight - 0.5) * 10);
  });
}
