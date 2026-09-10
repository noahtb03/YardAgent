export const EYE_HEIGHT = 5.5 * .3048;
export const BODY_RADIUS = .23;
export const groundHeight = (x, z) => .012 * Math.sin(x*1.3) * Math.sin(-z*1.7);

export function canStand(x, z, width, length, obstacles, radius = BODY_RADIUS) {
  if (!Number.isFinite(x) || !Number.isFinite(z) || x < radius || x > width-radius || z > -radius || z < -length+radius) return false;
  return !obstacles.some(([left, near, right, far]) => {
    const dx = x - Math.max(left, Math.min(x, right));
    const dz = z - Math.max(near, Math.min(z, far));
    return dx*dx + dz*dz < radius*radius;
  });
}

export function spawnPoint(width, length, obstacles) {
  // Prefer the photographer's near edge, then search free space in the yard.
  const step = Math.max(.4, Math.max(width,length)/100);
  for (let depth = .45; depth < length-BODY_RADIUS; depth += step) {
    for (let offset = 0; offset < width/2; offset += step) {
      for (const x of [width/2+offset,width/2-offset]) {
        if (canStand(x,-depth,width,length,obstacles)) return { x, z: -depth };
      }
    }
  }
  return null;
}

export function moveWithCollision(position, dx, dz, width, length, obstacles) {
  // Substeps prevent crossing thin fences/lights even after a delayed frame.
  const steps = Math.max(1, Math.ceil(Math.hypot(dx,dz)/.08));
  let { x, z } = position;
  for (let i=0; i<steps; i++) {
    if (canStand(x+dx/steps,z,width,length,obstacles)) x += dx/steps;
    if (canStand(x,z+dz/steps,width,length,obstacles)) z += dz/steps;
  }
  return { x, z };
}
