import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const indexPath = new URL('../index.html', import.meta.url);
const cssPath = new URL('../public/static/hero.css', import.meta.url);
const jsPath = new URL('../public/static/hero.js', import.meta.url);

test('hero puts two portraits and a conversation strand canvas around one headline and one button', async () => {
  const [index, css, js] = await Promise.all([
    readFile(indexPath, 'utf8'),
    readFile(cssPath, 'utf8'),
    readFile(jsPath, 'utf8'),
  ]);

  const hero = index.match(/<section class="hx"[\s\S]*?<\/section>/)?.[0] ?? '';
  assert.match(hero, /hero-man\.webp/);
  assert.match(hero, /hero-woman\.webp/);
  assert.match(hero, /<canvas class="hx-strands" aria-hidden="true">/);
  assert.match(hero, /<h1 id="hero-title">Someone might see/);
  assert.match(hero, /class="hx-cta"[^>]*>Meet Omiryn</);
  assert.match(hero, /data-app-link/);
  assert.match(index, /hero\.js/);

  // Both portraits carry alt text, since they are content, not decoration.
  const alts = [...hero.matchAll(/<img[^>]*alt="([^"]+)"/g)];
  assert.equal(alts.length, 2);

  // Landing.css gives every section 120px/48px padding; the hero must opt out.
  assert.match(css, /\.hx \{[^}]*padding: 0;/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(js, /prefers-reduced-motion: reduce/);
  assert.match(js, /IntersectionObserver/);
});
