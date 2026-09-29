// Home page motion. One main animation per section:
// hero floating people, chat demo, venn, reasons marquee, card stack.
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

/* ─────────── Hero: floating people ─────────── */
// Portraits float around the headline. Every few seconds two of them light up,
// a curved line draws between them under the text, and a short reason appears.
const FLOAT_REASONS = [
  "both hate small talk",
  "same chaotic humor",
  "both overthink at 2am",
  "different views, zero drama",
  "same taste in bad movies",
  "chai loyalists",
  "both love long walks",
];
// x, y in % of the hero; size in px. Desktop keeps the centre clear for text.
const DESKTOP_SPOTS = [
  [11, 26, 116], [21, 54, 82], [9, 78, 100], [27, 86, 64],
  [89, 26, 108], [79, 54, 86], [91, 78, 96], [73, 86, 68],
  [33, 13, 54], [67, 13, 54],
];
const DESKTOP_PAIRS = [[0, 5], [1, 6], [2, 4], [3, 7], [1, 4], [2, 5], [0, 6], [3, 5]];
const MOBILE_SPOTS = [[14, 79, 64], [38, 91, 70], [62, 79, 76], [86, 91, 62]];
const MOBILE_PAIRS = [[0, 2], [1, 3], [0, 3], [1, 2]];

const hero = $("#hero");
const floatLayer = $("#o-float");
const floatPath = $("#o-float-path");
const floatChip = $("#o-float-chip");
let floaters = [];
let pairs = DESKTOP_PAIRS;

function buildFloat() {
  $$(".o-floater", floatLayer).forEach((el) => el.remove());
  const mobile = window.matchMedia("(max-width: 760px)").matches;
  const spots = mobile ? MOBILE_SPOTS : DESKTOP_SPOTS;
  pairs = mobile ? MOBILE_PAIRS : DESKTOP_PAIRS;
  floaters = spots.map(([x, y, size], i) => {
    const el = document.createElement("span");
    el.className = "o-floater";
    el.style.left = `${x}%`;
    el.style.top = `${y}%`;
    el.style.setProperty("--s", `${size}px`);
    el.dataset.depth = (size / 120).toFixed(2);
    el.innerHTML = `<img src="${photo(i)}" alt="" decoding="async">`;
    floatLayer.appendChild(el);
    return el;
  });
  const svg = $("#o-float-lines");
  svg.setAttribute("viewBox", `0 0 ${floatLayer.offsetWidth} ${floatLayer.offsetHeight}`);
}
buildFloat();

function centerOf(el) {
  const box = floatLayer.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2 - box.left, y: r.top + r.height / 2 - box.top };
}

let pairIndex = 0;
function connectPair() {
  const [ia, ib] = pairs[pairIndex % pairs.length];
  pairIndex += 1;
  const a = floaters[ia];
  const b = floaters[ib];
  if (!a || !b) return;
  const p1 = centerOf(a);
  const p2 = centerOf(b);
  // Curve dips below both people so it passes under the headline and button.
  const cx = (p1.x + p2.x) / 2;
  const h = floatLayer.offsetHeight;
  const cy = Math.min(Math.max(p1.y, p2.y) + h * 0.16, h * 0.9);
  floatPath.setAttribute("d", `M${p1.x},${p1.y} Q${cx},${cy} ${p2.x},${p2.y}`);
  const len = floatPath.getTotalLength();
  const mid = floatPath.getPointAtLength(len / 2);
  floatChip.textContent = FLOAT_REASONS[pairIndex % FLOAT_REASONS.length];
  floatChip.style.left = `${mid.x}px`;
  floatChip.style.top = `${mid.y}px`;

  gsap.timeline()
    .call(() => { a.classList.add("is-match"); b.classList.add("is-match"); })
    .fromTo(floatPath, { strokeDasharray: len, strokeDashoffset: len, autoAlpha: 1 }, { strokeDashoffset: 0, duration: 0.9, ease: "power2.inOut" })
    .fromTo(floatChip, { autoAlpha: 0, scale: 0.7, y: 10 }, { autoAlpha: 1, scale: 1, y: 0, duration: 0.45, ease: "back.out(2.2)" }, "-=0.3")
    .to({}, { duration: 1.6 })
    .to([floatPath, floatChip], { autoAlpha: 0, duration: 0.4 })
    .call(() => { a.classList.remove("is-match"); b.classList.remove("is-match"); });
}

function floatIdle() {
  floaters.forEach((el, i) => {
    gsap.to(el, {
      y: gsap.utils.random(-14, 14),
      x: gsap.utils.random(-8, 8),
      rotation: gsap.utils.random(-4, 4),
      duration: gsap.utils.random(3, 5),
      delay: i * 0.1,
      repeat: -1,
      yoyo: true,
      ease: "sine.inOut",
    });
  });
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
  // Hero intro: words rise, then subtext and button, then the people pop in.
  gsap.timeline({ defaults: { ease: "expo.out" } })
    .from(".o-h1 .w > span", { yPercent: 110, duration: 0.9, stagger: 0.07 })
    .from("[data-intro]", { y: 20, autoAlpha: 0, duration: 0.8, stagger: 0.1 }, "-=0.6")
    .from(".o-floater", { scale: 0, autoAlpha: 0, duration: 0.8, stagger: { each: 0.06, from: "random" }, ease: "back.out(1.8)" }, 0.3);
  floatIdle();
  gsap.delayedCall(2, connectPair);
  setInterval(() => { if (!document.hidden) connectPair(); }, 3400);

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

    // Portraits drift with the cursor; bigger (closer) faces move more.
    const layerX = gsap.quickTo(floatLayer, "x", { duration: 1.2, ease: "power3" });
    const layerY = gsap.quickTo(floatLayer, "y", { duration: 1.2, ease: "power3" });
    hero.addEventListener("pointermove", (e) => {
      const r = hero.getBoundingClientRect();
      layerX(((e.clientX - r.left) / r.width - 0.5) * -24);
      layerY(((e.clientY - r.top) / r.height - 0.5) * -16);
    });
  }
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    gsap.killTweensOf(floaters);
    buildFloat();
    if (!reduce) floatIdle();
  }, 250);
});
