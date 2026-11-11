export interface FloorPoint { x: number; y: number }
export interface FloorDimensions { width: number; height: number; itemWidth: number; itemHeight: number }
const inset = { left: 22, right: 22, top: 58, bottom: 36 };
export const DEFAULT_FLOOR_SNAP = true;
export const FLOOR_GRID_STEP = 16;
// A radial tile's dot sits at its centre, so its tile origin is half a step
// before the first snap anchor. Painting and pointer maths share these values.
export const FLOOR_GRID_BACKGROUND = {
  backgroundSize: `${FLOOR_GRID_STEP}px ${FLOOR_GRID_STEP}px`,
  backgroundPosition: `${inset.left - FLOOR_GRID_STEP / 2}px ${inset.top - FLOOR_GRID_STEP / 2}px`,
  backgroundImage: `radial-gradient(circle at ${FLOOR_GRID_STEP / 2}px ${FLOOR_GRID_STEP / 2}px, #c9d1bf 1px, transparent 1px)`,
};
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

export function floorBounds(size: FloorDimensions) {
  return { left: inset.left, top: inset.top, width: Math.max(1, size.width - inset.left - inset.right - size.itemWidth), height: Math.max(1, size.height - inset.top - inset.bottom - size.itemHeight) };
}
/** Both painting and hit testing use this exact coordinate space. */
export function floorPixels(point: FloorPoint, size: FloorDimensions): FloorPoint {
  const box = floorBounds(size);
  return { x: box.left + clamp(point.x, 0, 1000) / 1000 * box.width, y: box.top + clamp(point.y, 0, 1000) / 1000 * box.height };
}
export function floorCoordinates(pixel: FloorPoint, size: FloorDimensions, snap = false): FloorPoint {
  const box = floorBounds(size);
  const local = { x: pixel.x - box.left, y: pixel.y - box.top };
  if (snap) {
    // At the edges choose the last grid point that still fits the resource.
    local.x = clamp(Math.round(local.x / FLOOR_GRID_STEP) * FLOOR_GRID_STEP, 0, Math.floor(box.width / FLOOR_GRID_STEP) * FLOOR_GRID_STEP);
    local.y = clamp(Math.round(local.y / FLOOR_GRID_STEP) * FLOOR_GRID_STEP, 0, Math.floor(box.height / FLOOR_GRID_STEP) * FLOOR_GRID_STEP);
  }
  return { x: Math.round(clamp(local.x / box.width * 1000, 0, 1000)), y: Math.round(clamp(local.y / box.height * 1000, 0, 1000)) };
}
export function pointerFloorPosition(client: FloorPoint, origin: FloorPoint, grab: FloorPoint, size: FloorDimensions, snap = false): FloorPoint {
  return floorCoordinates({ x: client.x - origin.x - grab.x, y: client.y - origin.y - grab.y }, size, snap);
}
