// Home page motion: hero chat demo, marquee, scroll reveals, venn, card stack.
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

/* ─────────── Hero chat demo ─────────── */
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

  tl.call(() => $(".o-phone").classList.add("is-thinking"));
  tl.to({}, { duration: 0.3 });
  tl.fromTo(matchPop, { autoAlpha: 0, y: 40, scale: 0.8, rotation: -6 }, {
    autoAlpha: 1, y: 0, scale: 1, rotation: -3, duration: 0.8, ease: "elastic.out(1, 0.6)",
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
  feed.innerHTML = "";
  slots.innerHTML = "";
  $(".o-phone").classList.remove("is-thinking");
  gsap.set([feed, slots], { autoAlpha: 1 });
  gsap.set(matchPop, { autoAlpha: 0 });
  demo = playDemo();
}

let demo = null;
if (reduce) {
  renderStaticDemo();
  $(".v-match .count").textContent = "86";
} else {
  gsap.set(matchPop, { autoAlpha: 0 });
  demo = playDemo();
  document.addEventListener("visibilitychange", () => {
    if (!demo) return;
    document.hidden ? demo.pause() : demo.resume();
  });
}

/* ─────────── Everything below is motion only ─────────── */
if (!reduce) {
  // Intro: headline words rise from a mask, the rest follows.
  gsap.timeline({ defaults: { ease: "expo.out" } })
    .from(".o-h1 .w > span", { yPercent: 110, duration: 0.8, stagger: 0.06 })
    .from("[data-intro]", { y: 24, autoAlpha: 0, duration: 0.9, stagger: 0.08 }, "-=0.8")
    .from(".o-phone", { y: 60, autoAlpha: 0, rotation: 4, duration: 0.9 }, 0.1)
    .from(".o-sticker", { scale: 0, rotation: -30, stagger: 0.12, duration: 0.8, ease: "back.out(2.5)" }, 0.8);

  // Stickers bob gently.
  $$(".o-sticker").forEach((el, i) => {
    gsap.to(el, { y: i % 2 ? 10 : -10, rotation: `+=${i % 2 ? 4 : -4}`, duration: 2.6 + i * 0.4, repeat: -1, yoyo: true, ease: "sine.inOut" });
  });

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

  // Step visuals play when their card appears.
  ScrollTrigger.create({
    trigger: ".o-steps",
    start: "top 75%",
    once: true,
    onEnter: () => {
      gsap.from(".v-chat .b", { y: 12, autoAlpha: 0, scale: 0.9, stagger: 0.45, duration: 0.5, ease: "back.out(2)", delay: 0.3 });
      gsap.from(".v-tags .t", { scale: 0, rotation: () => gsap.utils.random(-20, 20), stagger: 0.12, duration: 0.6, ease: "back.out(2.5)", delay: 0.4 });
      gsap.fromTo(".v-match .meter i", { width: "0%" }, { width: "86%", duration: 1.6, ease: "power3.out", delay: 0.6 });
      const counter = { v: 0 };
      gsap.to(counter, { v: 86, duration: 1.6, ease: "power3.out", delay: 0.6, onUpdate: () => { $(".v-match .count").textContent = Math.round(counter.v); } });
    },
  });

  // Venn: circles slide together as you scroll, shared traits pop in the middle.
  gsap.timeline({ scrollTrigger: { trigger: ".venn", start: "top 85%", end: "center 55%", scrub: 0.8 } })
    .fromTo(".venn-a", { xPercent: -30, rotation: -8 }, { xPercent: 0, rotation: 0 }, 0)
    .fromTo(".venn-b", { xPercent: 30, rotation: 8 }, { xPercent: 0, rotation: 0 }, 0)
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

    // 3D tilt on step cards.
    $$(".tilt").forEach((card) => {
      card.addEventListener("pointermove", (e) => {
        const r = card.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width - 0.5;
        const py = (e.clientY - r.top) / r.height - 0.5;
        gsap.to(card, { rotationY: px * 10, rotationX: -py * 10, transformPerspective: 800, duration: 0.4, ease: "power2.out", overwrite: "auto" });
      });
      card.addEventListener("pointerleave", () => gsap.to(card, { rotationY: 0, rotationX: 0, duration: 0.6, ease: "elastic.out(1, 0.5)" }));
    });

    // The phone leans toward the cursor a little.
    const stage = $(".o-stage");
    stage.addEventListener("pointermove", (e) => {
      const r = stage.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5;
      const py = (e.clientY - r.top) / r.height - 0.5;
      gsap.to(".o-phone", { rotationY: px * 8, rotationX: -py * 8, transformPerspective: 1000, duration: 0.6, overwrite: "auto" });
    });
    stage.addEventListener("pointerleave", () => gsap.to(".o-phone", { rotationY: 0, rotationX: 0, duration: 0.8 }));
  }
}
