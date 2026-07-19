/**
 * weight_targeting.js — weight-space fisheye targeting for AetherBrowser's agent (port of weight_targeting.py).
 *
 * The agent shouldn't click raw pixels (brittle). Every target carries an IMPORTANCE; as the agent's aim nears a
 * target it grows toward click-size and others shrink, so being NEAR the right thing is enough. Importance widens
 * the BASIN (flatter falloff -> captures from farther), not the final size. The screen pixels never change — this
 * is the agent's targeting lens. Ref: weight_targeting.py (self-test PASS).
 */
'use strict';

const MIN_SIZE = 8.0;     // px: far/unimportant effective hit radius
const CLICK_SIZE = 44.0;  // px: comfortable click target (HIG ~44)
const SCALE = 140.0;      // px: proximity falloff
const SNAP = 0.55;        // capture threshold

function dist(ax, ay, bx, by) { return Math.hypot(ax - bx, ay - by); }

function effProx(t, cx, cy) {
  const d = dist(t.x, t.y, cx, cy);
  const prox = 1.0 / (1.0 + (d / SCALE) ** 2);
  const exponent = 1.0 / (0.45 + 1.1 * (t.importance || 0));   // imp0 -> steep/tiny basin, imp1 -> flat/wide basin
  return Math.pow(prox, exponent);
}

function effectiveSize(t, cx, cy) { return MIN_SIZE + (CLICK_SIZE - MIN_SIZE) * effProx(t, cx, cy); }

/** Apply the lens at (cx,cy): each target's pull+size, and the SNAP target (the one the cursor is on). */
function lens(targets, cx, cy) {
  const rows = targets.map((t) => ({
    id: t.id, x: t.x, y: t.y, text: t.text || '', pull: effProx(t, cx, cy), size: effectiveSize(t, cx, cy),
  }));
  rows.sort((a, b) => b.pull - a.pull);
  const top = rows[0] || null;
  const snap = top && top.pull >= SNAP ? top.id : null;
  return { rows, snap, snapTarget: snap ? top : null, topPull: top ? top.pull : 0 };
}

module.exports = { lens, effectiveSize, effProx, MIN_SIZE, CLICK_SIZE, SCALE, SNAP };

// self-test mirrors weight_targeting.py: important target grows to click-size + captures; distractor stays small
if (require.main === module) {
  const T = [
    { id: 'submit', x: 500, y: 400, importance: 0.92 },
    { id: 'cancel', x: 300, y: 400, importance: 0.25 },
    { id: 'nav', x: 120, y: 80, importance: 0.15 },
  ];
  let cx0 = 320, cy0 = 240, capturedAt = null, sizes = [];
  for (let i = 0; i <= 6; i++) {
    const f = i / 6, cx = cx0 + (500 - cx0) * f, cy = cy0 + (400 - cy0) * f;
    const L = lens(T, cx, cy); const me = L.rows.find((r) => r.id === 'submit');
    sizes.push(me.size);
    if (L.snap === 'submit' && capturedAt === null) capturedAt = f;
  }
  const start = sizes[0], end = sizes[sizes.length - 1];
  const cancelSize = lens(T, 500, 400).rows.find((r) => r.id === 'cancel').size;
  const hi = effectiveSize({ x: 400, y: 240, importance: 0.9 }, 320, 240);
  const lo = effectiveSize({ x: 240, y: 240, importance: 0.2 }, 320, 240);
  const ok = end >= CLICK_SIZE - 0.5 && end > start * 1.4 && capturedAt !== null && capturedAt < 1
    && cancelSize < CLICK_SIZE * 0.5 && hi > lo + 4;
  console.log(`submit ${start.toFixed(1)}->${end.toFixed(1)}px, captured@${capturedAt}, distractor ${cancelSize.toFixed(1)}px, imp ${hi.toFixed(1)}>${lo.toFixed(1)}`);
  console.log('JS lens self-test:', ok ? 'PASS (matches weight_targeting.py)' : 'FAIL');
  process.exit(ok ? 0 : 1);
}
