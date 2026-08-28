import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const indexPath = new URL('../index.html', import.meta.url);
const themePath = new URL('../public/static/landing-theme-connection.css', import.meta.url);
const signalPath = new URL('../public/static/connection-signal-field.js', import.meta.url);

test('connection hero makes the thought field the focal point', async () => {
  const [index, theme, signal] = await Promise.all([
    readFile(indexPath, 'utf8'),
    readFile(themePath, 'utf8'),
    readFile(signalPath, 'utf8'),
  ]);

  assert.match(index, /omiryn-indian-connection-hero-v2\.webp/);
  assert.match(index, /connection-thought-field/);
  assert.match(index, /connection-thought--left/);
  assert.match(index, /connection-thought--right/);
  assert.match(index, /connection-particle-cloud/);
  assert.match(index, /connection-signal-field/);
  assert.match(index, /data-signal-traveler/);
  assert.match(index, /connection-signal-field\.js/);
  assert.match(index, /hero-whisper/);
  const hero = index.match(/<section class="hero hero--connection"[\s\S]*?<\/section>/)?.[0] ?? '';
  assert.doesNotMatch(hero, /<h1/);
  assert.doesNotMatch(hero, /hero-actions/);
  assert.match(theme, /@keyframes connection-thought-drift-left/);
  assert.match(theme, /connection-signal-route/);
  assert.match(theme, /box-shadow: -32px -13px 0 -1px currentColor/);
  assert.match(theme, /transform: scale\(1\)/);
  assert.match(theme, /prefers-reduced-motion: reduce[\s\S]*\.connection-thought-field/);
  assert.match(signal, /const signalCycles/);
  assert.match(signal, /const backgroundThoughts/);
  assert.match(signal, /same pace/);
  assert.match(signal, /getAttribute\('href'\)/);
});
