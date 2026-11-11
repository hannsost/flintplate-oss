import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';
const file = new URL('../lib/flintplate-floor-geometry.ts', import.meta.url);
const compiled = ts.transpileModule(await fs.readFile(file, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { DEFAULT_FLOOR_SNAP, FLOOR_GRID_BACKGROUND, FLOOR_GRID_STEP, floorPixels, floorCoordinates, pointerFloorPosition } = await import(`data:text/javascript,${encodeURIComponent(compiled)}`);
assert.equal(DEFAULT_FLOOR_SNAP, true);
assert.equal(FLOOR_GRID_BACKGROUND.backgroundSize, '16px 16px');
assert.equal(FLOOR_GRID_BACKGROUND.backgroundPosition, '14px 50px');
assert.match(FLOOR_GRID_BACKGROUND.backgroundImage, /at 8px 8px/);
const tileOrigin = FLOOR_GRID_BACKGROUND.backgroundPosition.split(' ').map(parseFloat);
const dot = { x: tileOrigin[0] + FLOOR_GRID_STEP / 2, y: tileOrigin[1] + FLOOR_GRID_STEP / 2 };
function gridDistance(value, firstDot) { const remainder = ((value - firstDot) % FLOOR_GRID_STEP + FLOOR_GRID_STEP) % FLOOR_GRID_STEP; return Math.min(remainder, FLOOR_GRID_STEP - remainder); }
for (const width of [540, 960, 1440]) for (const height of [355, 470]) for (const itemWidth of [100, 132]) {
  const size = { width, height, itemWidth, itemHeight: itemWidth === 100 ? 77 : 85 };
  for (const point of [{ x: 0, y: 0 }, { x: 123, y: 987 }, { x: 500, y: 500 }, { x: 1000, y: 1000 }]) {
    const pixel = floorPixels(point, size);
    assert.deepEqual(floorCoordinates(pixel, size), point);
    assert(pixel.x >= 0 && pixel.x + itemWidth <= width);
    assert(pixel.y >= 0 && pixel.y + size.itemHeight <= height);
    for (const grab of [{ x: 2, y: 5 }, { x: itemWidth - 3, y: size.itemHeight - 2 }]) {
      const origin = { x: -180, y: 273 }; // Scrolled canvas within the viewport.
      assert.deepEqual(pointerFloorPosition({ x: origin.x + pixel.x + grab.x, y: origin.y + pixel.y + grab.y }, origin, grab, size), point);
    }
  }
  assert.deepEqual(floorCoordinates({ x: -999, y: -999 }, size, true), { x: 0, y: 0 });
  for (const target of [{ x: 59, y: 111 }, { x: 287, y: 241 }, { x: 9999, y: 9999 }]) {
    const landing = floorPixels(floorCoordinates(target, size, DEFAULT_FLOOR_SNAP), size);
    // The API stores integer 0..1000 positions: its subpixel rounding stays below one pixel.
    assert(gridDistance(landing.x, dot.x) < 1 && gridDistance(landing.y, dot.y) < 1);
    assert(landing.x + itemWidth <= width && landing.y + size.itemHeight <= height);
  }
  assert.deepEqual(floorCoordinates({ x: 9999, y: 9999 }, size, false), { x: 1000, y: 1000 });
  const snapped = floorPixels(floorCoordinates({ x: 59, y: 111 }, size, true), size);
  assert(Math.abs(snapped.x - 54) < 1 && Math.abs(snapped.y - 106) < 1);
}
console.log('Floor geometry: paint/drop inverse, edge bounds, scroll offsets, arbitrary grab points, both resource sizes, default snap and visible16px grid alignment passed.');
