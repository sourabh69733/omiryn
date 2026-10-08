// Home page motion. One main animation per section:
// hero vibe fingerprints, pinned how-it-works story, venn, reasons marquee, card stack.
// Everything renders in a readable final state when the user prefers reduced motion.
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = window.matchMedia("(pointer: fine)").matches;
// Dark text on the yellow highlight, so a highlighted word stays readable inside a dark bubble.
const MARK_INK = "#18181b";
// Phones and tablets get the story as a simple list plus one readable chat; the pinned scroll story
// needs the side-by-side room of a wide screen.
const compact = window.matchMedia("(max-width: 1024px)").matches;
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
function setupMarquee() {
  $$(".o-marquee-row").forEach((row, rowIndex) => {
    const list = rowIndex ? [...REASONS].reverse() : REASONS;
    const chips = list
      .map((text, i) => `<span class="o-chip-m"><span class="pair"><span data-avatar="${i}"></span><span data-avatar="${i + 3}"></span></span><small>matched because</small> ${text}</span>`)
      .join("");
    // Two copies so the CSS loop is seamless.
    row.innerHTML = `<div class="o-marquee-track">${chips}</div><div class="o-marquee-track" aria-hidden="true">${chips}</div>`;
    paintAvatars(row);
  });
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

/* ─────────── Vibe fingerprints ─────────── */
// Each .blob gets an SVG shape that slowly wobbles like a lava lamp. Shapes are
// drawn on one shared ticker; overlapping blobs blend through mix-blend-mode.
const blobs = [];
let blobId = 0;

function makeBlob(el, seed) {
  const id = `bg${(blobId += 1)}`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 200 200");
  svg.setAttribute("class", "blob-shape");
  svg.innerHTML = `
    <defs>
      <radialGradient id="${id}" cx="40%" cy="35%" r="75%">
        <stop class="c1" offset="0" stop-color="${el.dataset.c1}"/>
        <stop class="c2" offset="1" stop-color="${el.dataset.c2}"/>
      </radialGradient>
    </defs>
    <path fill="url(#${id})"/>`;
  el.prepend(svg);
  const blob = { el, path: svg.querySelector("path"), stops: svg.querySelectorAll("stop"), seed, energy: 1, visible: true };
  blobs.push(blob);
  return blob;
}

function setBlobColors(blob, c1, c2) {
  blob.stops[0].setAttribute("stop-color", c1);
  blob.stops[1].setAttribute("stop-color", c2);
}

// Smooth closed shape through points on a wobbling circle (Catmull-Rom to Bezier).
function blobPath(t, seed, energy) {
  const n = 9;
  const pts = [];
  for (let i = 0; i < n; i += 1) {
    const a = (i / n) * Math.PI * 2;
    const wobble =
      0.07 * Math.sin(3 * a + t * 0.9 + seed) +
      0.05 * Math.sin(5 * a - t * 1.2 + seed * 2.1) +
      0.04 * Math.sin(2 * a + t * 0.55 + seed * 0.7);
    const r = 84 * (1 + wobble * energy);
    pts.push([100 + Math.cos(a) * r, 100 + Math.sin(a) * r]);
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n; i += 1) {
    const p0 = pts[(i - 1 + n) % n];
    const p1 = pts[i];
    const p2 = pts[(i + 1) % n];
    const p3 = pts[(i + 2) % n];
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += `C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return `${d}Z`;
}

function drawBlobs(time = 0) {
  blobs.forEach((b) => {
    if (b.visible) b.path.setAttribute("d", blobPath(time, b.seed, b.energy));
  });
}

$$(".blob").forEach((el, i) => makeBlob(el, i * 1.7));
drawBlobs(0);

// Only animate shapes that are on screen.
const blobObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    const b = blobs.find((x) => x.el === entry.target);
    if (b) b.visible = entry.isIntersecting;
  });
});
blobs.forEach((b) => blobObserver.observe(b.el));

/* ─────────── Hero: you meet someone new, again and again ─────────── */
const PARTNERS = [
  { face: 4, c: ["#fbcfe8", "#f472b6"], traits: ["Football", "Gym at 6am"], shared: "Bad puns", reason: "both laugh at bad puns" },
  { face: 2, c: ["#fde68a", "#f59e0b"], traits: ["Coffee person", "Early bird"], shared: "No small talk", reason: "both hate small talk" },
  { face: 5, c: ["#a7f3d0", "#10b981"], traits: ["Not so sure about god", "Books"], shared: "2am thinker", reason: "same 2am overthinking" },
  { face: 8, c: ["#bae6fd", "#0ea5e9"], traits: ["Football", "Hills > beaches"], shared: "Side quests", reason: "both live for side quests" },
];
const vs = $("#vs");
const you = blobs.find((b) => b.el.id === "blob-you");
const them = blobs.find((b) => b.el.id === "blob-them");
const vsGlow = $("#vs-glow");
const vsReason = $("#vs-reason");
let partnerIndex = 0;
let heroLoop = null;
let heroVisible = true;

// Pause the meet loop while the hero is off screen; it resumes where it left off.
new IntersectionObserver(([entry]) => {
  heroVisible = entry.isIntersecting;
  if (heroLoop) heroVisible ? heroLoop.resume() : heroLoop.pause();
}).observe($("#hero"));

function loadPartner(partner) {
  $(".blob-face", them.el).src = photo(partner.face - 1);
  setBlobColors(them, partner.c[0], partner.c[1]);
  const [t1, t2, shared] = $$(".blob-chip", them.el);
  t1.textContent = partner.traits[0];
  t2.textContent = partner.traits[1];
  shared.textContent = partner.shared;
  $(".blob-chip.is-shared", you.el).textContent = partner.shared;
  vsReason.textContent = `✦ ${partner.reason}`;
}

function showMerged() {
  // Final, readable state: both people overlapping with the shared reason.
  loadPartner(PARTNERS[0]);
  gsap.set(you.el, { left: "41.5%" });
  gsap.set(them.el, { left: "58.5%", autoAlpha: 1 });
  gsap.set([vsGlow, vsReason], { autoAlpha: 1, scale: 1 });
}

function meetCycle() {
  const partner = PARTNERS[partnerIndex % PARTNERS.length];
  partnerIndex += 1;
  const theirChips = $$(".blob-chip", them.el);
  const sharedChips = [$(".blob-chip.is-shared", you.el), $(".blob-chip.is-shared", them.el)];

  heroLoop = gsap.timeline({ paused: !heroVisible, onComplete: meetCycle });
  return heroLoop
    .call(() => loadPartner(partner))
    .set(them.el, { left: "112%", autoAlpha: 0, scale: 0.6 })
    .set([vsGlow, vsReason], { autoAlpha: 0, scale: 0.6 })
    .set(sharedChips, { autoAlpha: 0, scale: 0.6, y: 0 })
    // Someone new arrives.
    .to(them.el, { left: "70%", autoAlpha: 1, scale: 1, duration: 1.1, ease: "expo.out" })
    .fromTo(theirChips.slice(0, 2), { autoAlpha: 0, scale: 0.6 }, { autoAlpha: 1, scale: 1, stagger: 0.1, duration: 0.4, ease: "back.out(2)" }, "-=0.5")
    .to(sharedChips, { autoAlpha: 1, scale: 1, duration: 0.4, ease: "back.out(2)" }, "-=0.2")
    .to({}, { duration: 0.5 })
    // They drift together; the overlap lights up.
    .to(you.el, { left: "41.5%", duration: 1.3, ease: "power3.inOut" }, "meet")
    .to(them.el, { left: "58.5%", duration: 1.3, ease: "power3.inOut" }, "meet")
    .to(sharedChips, { autoAlpha: 0, scale: 0.6, y: -10, duration: 0.3 }, "meet")
    .to(vsGlow, { autoAlpha: 1, scale: 1, duration: 0.7, ease: "back.out(1.6)" }, "meet+=0.9")
    .to(vsReason, { autoAlpha: 1, scale: 1, duration: 0.5, ease: "back.out(2.2)" }, "meet+=1.1")
    .to([you, them], { energy: 1.8, duration: 0.6, yoyo: true, repeat: 1, ease: "sine.inOut" }, "meet+=0.9")
    .to({}, { duration: 2.2 })
    // They part ways; someone else is next.
    .to([vsGlow, vsReason], { autoAlpha: 0, scale: 0.8, duration: 0.35 })
    .to(theirChips.slice(0, 2), { autoAlpha: 0, duration: 0.25 }, "<")
    .to(them.el, { left: "112%", autoAlpha: 0, scale: 0.7, duration: 0.8, ease: "power2.in" }, "part")
    .to(you.el, { left: "30%", duration: 1, ease: "power3.inOut" }, "part");
}

/* ─────────── How it works: pinned scroll story ─────────── */
const story = $("#how");
const stage = $("#o-story-stage");
const sYou = blobs.find((b) => b.el.id === "s-you");
const sThem = blobs.find((b) => b.el.id === "s-them");
const bubbles = $$(".o-story .o-msg");
const marks = $$(".o-story mark");
const steps = $$(".o-story .st");
const matchPop = $("#o-matchpop");
const tagLayer = $("#s-tags");

// One flying tag per highlighted phrase.
const flyTags = marks.map((mark, i) => {
  const tag = document.createElement("span");
  tag.className = `s-tag c${i + 1}`;
  tag.textContent = mark.dataset.tag;
  tagLayer.appendChild(tag);
  return tag;
});

// Positions inside the (possibly scaled) stage, in unscaled stage pixels.
function stagePoint(el) {
  const box = stage.getBoundingClientRect();
  const k = box.width / stage.offsetWidth || 1;
  const r = el.getBoundingClientRect();
  return { x: (r.left + r.width / 2 - box.left) / k, y: (r.top + r.height / 2 - box.top) / k };
}

// On stacked layouts the stage sits under the text, so shrink it to fit the screen.
function fitStage() {
  const view = $(".o-story-view");
  if (window.innerWidth > 1024) {
    view.style.removeProperty("--k");
    return;
  }
  const textHeight = $(".o-story-text").offsetHeight;
  const room = window.innerHeight - textHeight - 110;
  const k = Math.max(0.42, Math.min(window.innerWidth / 600, room / 560, 0.85));
  view.style.setProperty("--k", k.toFixed(3));
}
fitStage();
window.addEventListener("resize", fitStage);

function storyStatic() {
  story.classList.add("is-static");
  gsap.set(marks, { backgroundSize: "100% 100%", color: MARK_INK });
}

// Phones: steps as a list, the chat at full size, then the match. The chat is always visible (a
// fast flick must never show an empty phone); only the highlights and the match card animate in.
function storyCompact() {
  story.classList.add("is-static", "is-compact");
  if (reduce) {
    gsap.set(marks, { backgroundSize: "100% 100%", color: MARK_INK });
    return;
  }
  marks.forEach((mark) => {
    gsap.to(mark, { backgroundSize: "100% 100%", color: MARK_INK, duration: 0.6, ease: "power2.out", scrollTrigger: { trigger: mark, start: "top 80%", once: true } });
  });
  gsap.from(matchPop, { autoAlpha: 0, y: 30, scale: 0.94, duration: 0.6, ease: "back.out(1.6)", scrollTrigger: { trigger: matchPop, start: "top 90%", once: true } });
}

function buildStory() {
  story.classList.add("is-live");
  gsap.set(bubbles, { autoAlpha: 0, y: 16 });
  gsap.set(steps, { autoAlpha: 0, y: 30 });
  gsap.set(steps[0], { autoAlpha: 1, y: 0 });
  gsap.set(sYou.el, { scale: 0.55, autoAlpha: 0.5 });
  gsap.set(sThem.el, { xPercent: 140, autoAlpha: 0 });
  gsap.set(matchPop, { autoAlpha: 0, y: 40, scale: 0.9 });
  gsap.set(flyTags, { autoAlpha: 0 });

  const tl = gsap.timeline({
    defaults: { ease: "power2.out" },
    scrollTrigger: {
      trigger: story,
      start: "top top",
      end: "+=260%",
      pin: true,
      scrub: 0.7,
      invalidateOnRefresh: true,
      onUpdate: (self) => gsap.set("#o-story-bar", { scaleX: self.progress }),
    },
  });

  // 1. The chat types in.
  tl.to(bubbles, { autoAlpha: 1, y: 0, stagger: 0.16, duration: 0.2 }, 0);

  // 2. Highlighted words lift off and get absorbed into your vibe.
  tl.to(steps[0], { autoAlpha: 0, y: -30, duration: 0.15 }, 1)
    .to(steps[1], { autoAlpha: 1, y: 0, duration: 0.15 }, 1.05);
  marks.forEach((mark, i) => {
    const at = 1.05 + i * 0.22;
    const tag = flyTags[i];
    tl.to(mark, { backgroundSize: "100% 100%", color: MARK_INK, duration: 0.12 }, at)
      .fromTo(tag,
        { x: () => stagePoint(mark).x, y: () => stagePoint(mark).y, autoAlpha: 0, scale: 0.8 },
        { autoAlpha: 1, scale: 1, duration: 0.08 }, at + 0.05)
      .to(tag, { x: () => stagePoint(sYou.el).x, y: () => stagePoint(sYou.el).y, scale: 0.3, duration: 0.18, ease: "power2.in" }, at + 0.1)
      .to(tag, { autoAlpha: 0, duration: 0.04 }, at + 0.26)
      .to(sYou.el, { scale: 0.55 + (i + 1) * 0.15, autoAlpha: 0.6 + (i + 1) * 0.13, duration: 0.1, ease: "back.out(2)" }, at + 0.27);
  });

  // 3. Someone who fits arrives, you overlap, the match lands.
  tl.to(steps[1], { autoAlpha: 0, y: -30, duration: 0.15 }, 2)
    .to(steps[2], { autoAlpha: 1, y: 0, duration: 0.15 }, 2.05)
    .to(".o-story .o-phone", { autoAlpha: 0.18, scale: 0.92, duration: 0.3 }, 2)
    .to(sYou.el, { left: "45%", top: "38%", duration: 0.35, ease: "power2.inOut" }, 2.05)
    .to(sThem.el, { xPercent: 0, autoAlpha: 1, duration: 0.35, ease: "power2.inOut" }, 2.1)
    .fromTo(matchPop, { autoAlpha: 0, y: 40, scale: 0.9 }, { autoAlpha: 1, y: 0, scale: 1, duration: 0.25, ease: "back.out(1.8)" }, 2.5)
    .to({}, { duration: 0.25 });
  return tl;
}

/* ─────────── Start ─────────── */
// Hero runs now. Everything below the fold is set up in small steps once the
// browser is idle, or right away on the first scroll or anchor click. The
// motion is the same, it just stops competing with the first paint.
if (reduce) showMerged();

const belowFold = [
  setupMarquee,
  setupCards,
  () => (compact ? storyCompact() : reduce ? storyStatic() : buildStory()),
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
  // Hero intro: words rise, then subtext and button, then your vibe appears.
  gsap.timeline({ defaults: { ease: "expo.out" } })
    .from(".o-h1 .w > span", { yPercent: 110, duration: 0.9, stagger: 0.07 })
    .from("[data-intro]", { y: 20, autoAlpha: 0, duration: 0.8, stagger: 0.1 }, "-=0.6")
    .from(you.el, { scale: 0, autoAlpha: 0, duration: 1.2, ease: "elastic.out(1, 0.6)" }, 0.3)
    .add(meetCycle, 1);

  // Shapes wobble on the shared ticker.
  gsap.ticker.add((time) => drawBlobs(time));

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

  // The fingerprints lean toward the cursor a little.
  const vx = gsap.quickTo(vs, "x", { duration: 1.2, ease: "power3" });
  const vy = gsap.quickTo(vs, "y", { duration: 1.2, ease: "power3" });
  $("#hero").addEventListener("pointermove", (e) => {
    vx((e.clientX / window.innerWidth - 0.5) * 24);
    vy((e.clientY / window.innerHeight - 0.5) * 16);
  });
}
