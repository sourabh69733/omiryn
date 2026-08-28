const signalCycles = [
  { node: 'rhythm', left: 'slow Sundays', right: 'room to breathe', insight: 'same pace' },
  { node: 'comfort', left: 'old Hindi songs', right: 'music that feels like home', insight: 'familiarity' },
  { node: 'curiosity', left: 'asking better questions', right: 'conversations that linger', insight: 'curiosity' },
];

const backgroundThoughts = [
  ['left', 105, 150, -8, 'slow Sundays', 'mist'], ['left', 235, 168, -5, 'a quieter life', 'gold'],
  ['left', 390, 186, -2, 'old Hindi songs', 'mist'], ['left', 80, 205, -7, 'morning walks', 'coral'],
  ['left', 190, 224, -4, 'people who listen', 'mist'], ['left', 345, 241, -1, 'small dinners', 'gold'],
  ['left', 500, 258, 2, 'laughing until late', 'mist'], ['left', 120, 267, -6, 'room to breathe', 'gold'],
  ['left', 275, 286, -3, 'long train rides', 'mist'], ['left', 430, 304, 0, 'asking better questions', 'coral'],
  ['left', 70, 328, -5, 'a softer pace', 'mist'], ['left', 208, 345, -2, 'slow Sundays', 'gold'],
  ['left', 360, 362, 1, 'the way you see things', 'mist'], ['left', 505, 380, 3, 'music that feels like home', 'gold'],
  ['left', 125, 391, -4, 'conversations that linger', 'coral'], ['left', 278, 409, -1, 'curiosity over noise', 'mist'],
  ['left', 425, 427, 2, 'a familiar kind of ease', 'gold'], ['left', 178, 448, -3, 'people who notice', 'mist'],
  ['right', 1335, 150, 8, 'room to breathe', 'mist'], ['right', 1205, 168, 5, 'small dinners', 'gold'],
  ['right', 1050, 186, 2, 'morning walks', 'mist'], ['right', 1360, 205, 7, 'old Hindi songs', 'coral'],
  ['right', 1250, 224, 4, 'slow Sundays', 'mist'], ['right', 1095, 241, 1, 'a quieter life', 'gold'],
  ['right', 940, 258, -2, 'asking better questions', 'mist'], ['right', 1320, 267, 6, 'long train rides', 'gold'],
  ['right', 1165, 286, 3, 'people who listen', 'mist'], ['right', 1010, 304, 0, 'laughing until late', 'coral'],
  ['right', 1370, 328, 5, 'music that feels like home', 'mist'], ['right', 1232, 345, 2, 'a softer pace', 'gold'],
  ['right', 1080, 362, -1, 'conversations that linger', 'mist'], ['right', 935, 380, -3, 'the way you see things', 'gold'],
  ['right', 1315, 391, 4, 'curiosity over noise', 'coral'], ['right', 1162, 409, 1, 'a familiar kind of ease', 'mist'],
  ['right', 1015, 427, -2, 'people who notice', 'gold'], ['right', 1262, 448, 3, 'room to breathe', 'mist'],
];

const scene = document.querySelector('.connection-signal-field');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

if (scene) {
  const svgNamespace = 'http://www.w3.org/2000/svg';
  const backgroundLayer = document.createElementNS(svgNamespace, 'g');
  backgroundLayer.classList.add('connection-background-thoughts');

  for (const [side, x, y, rotation, label, tone] of backgroundThoughts) {
    const thought = document.createElementNS(svgNamespace, 'text');
    thought.classList.add('connection-background-thought', `connection-background-thought--${tone}`);
    thought.textContent = label;
    thought.setAttribute('x', String(x));
    thought.setAttribute('y', String(y));
    thought.setAttribute('text-anchor', side === 'left' ? 'start' : 'end');
    thought.setAttribute('transform', `rotate(${rotation} ${x} ${y})`);
    backgroundLayer.append(thought);
  }

  scene.insertBefore(backgroundLayer, scene.querySelector('.connection-signal-routes'));
}

if (scene && !reducedMotion) {
  const travelers = {
    left: scene.querySelector('[data-signal-traveler="left"]'),
    right: scene.querySelector('[data-signal-traveler="right"]'),
  };
  const insight = scene.querySelector('[data-signal-insight]');

  const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  const pointAt = (route, progress) => {
    const length = route.getTotalLength();
    return route.getPointAtLength(length * progress);
  };

  const placeTraveler = (element, route, progress, label, direction) => {
    const point = pointAt(route, progress);
    element.textContent = label;
    element.setAttribute('x', point.x);
    element.setAttribute('y', point.y);
    element.setAttribute('text-anchor', direction === 'left' ? 'end' : 'start');
    element.style.opacity = String(Math.sin(Math.min(progress, 1) * Math.PI));
  };

  const playCycle = (cycle) => new Promise((resolve) => {
    const leftRoute = scene.querySelector(`[data-signal-route="left ${cycle.node}"]`);
    const rightRoute = scene.querySelector(`[data-signal-route="right ${cycle.node}"]`);
    const leftPath = scene.querySelector(leftRoute.getAttribute('href'));
    const rightPath = scene.querySelector(rightRoute.getAttribute('href'));
    const node = scene.querySelector(`[data-signal-node="${cycle.node}"]`);
    const startedAt = performance.now();
    const travelDuration = 2600;

    leftRoute.classList.add('is-active');
    rightRoute.classList.add('is-active');
    node.classList.add('is-active');

    const frame = (now) => {
      const progress = Math.min((now - startedAt) / travelDuration, 1);
      placeTraveler(travelers.left, leftPath, progress, cycle.left, 'left');
      placeTraveler(travelers.right, rightPath, progress, cycle.right, 'right');

      if (progress < 1) {
        window.requestAnimationFrame(frame);
        return;
      }

      travelers.left.style.opacity = '0';
      travelers.right.style.opacity = '0';
      insight.textContent = cycle.insight;
      insight.setAttribute('x', '720');
      insight.setAttribute('y', node.getAttribute('cy'));
      insight.classList.add('is-visible');

      window.setTimeout(() => {
        insight.classList.remove('is-visible');
        leftRoute.classList.remove('is-active');
        rightRoute.classList.remove('is-active');
        node.classList.remove('is-active');
        resolve();
      }, 1300);
    };

    window.requestAnimationFrame(frame);
  });

  void (async () => {
    let index = 0;
    while (true) {
      await wait(1100);
      await playCycle(signalCycles[index]);
      index = (index + 1) % signalCycles.length;
    }
  })();
}
