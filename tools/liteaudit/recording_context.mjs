// This is a draw-command oracle, not a rasterizer. Keep transforms and paint
// boundaries so assertions observe what was submitted to Canvas, not intent.
export class RecordingPath2D {
  constructor(svg) { this.svg = svg; }
}
export class RecordingContext {
  constructor() {
    this.canvas = { width: 640, height: 480 };
    this.globalAlpha = 1;
    this.matrix = [1, 0, 0, 1, 0, 0];
    this.stack = [];
    this.reset();
  }
  reset() { this.calls = []; this.path = []; this.tag = 'stage'; }
  record(op, args = []) {
    this.calls.push({ op, args, tag: this.tag, matrix: [...this.matrix],
      alpha: this.globalAlpha, fillStyle: this.fillStyle, strokeStyle: this.strokeStyle,
      path: op === 'fill' || op === 'stroke' ? [...this.path] : undefined });
  }
  setTransform(...m) { this.matrix = m; this.record('setTransform', m); }
  translate(x, y) {
    const [a, b, c, d, e, f] = this.matrix;
    this.matrix = [a, b, c, d, e + a * x + c * y, f + b * x + d * y];
    this.record('translate', [x, y]);
  }
  scale(x, y) { const [a, b, c, d, e, f] = this.matrix; this.matrix = [a * x, b * x, c * y, d * y, e, f]; this.record('scale', [x, y]); }
  save() { this.stack.push({ matrix: [...this.matrix], globalAlpha: this.globalAlpha, fillStyle: this.fillStyle, strokeStyle: this.strokeStyle }); this.record('save'); }
  restore() { Object.assign(this, this.stack.pop()); this.record('restore'); }
  point(x, y) { const [a, b, c, d, e, f] = this.matrix; return [a * x + c * y + e, b * x + d * y + f]; }
  beginPath() { this.path = []; this.record('beginPath'); }
  closePath() { this.path.push({ op: 'closePath' }); this.record('closePath'); }
  moveTo(x, y) { this.path.push({ op: 'moveTo', point: this.point(x, y) }); this.record('moveTo', [x, y]); }
  lineTo(x, y) { this.path.push({ op: 'lineTo', point: this.point(x, y) }); this.record('lineTo', [x, y]); }
  quadraticCurveTo(cx, cy, x, y) { this.path.push({ op: 'lineTo', point: this.point(x, y) }); this.record('quadraticCurveTo', [cx, cy, x, y]); }
  arc(...values) { this.path.push({ op: 'arc', point: this.point(...values), radius: values[2] }); this.record('arc', values); }
  ellipse(...values) { this.path.push({ op: 'ellipse', point: this.point(...values), radius: [values[2], values[3]] }); this.record('ellipse', values); }
  rect(...values) { this.path.push({ op: 'rect', point: this.point(values[0], values[1]), size: [values[2], values[3]] }); this.record('rect', values); }
  roundRect(...values) { this.path.push({ op: 'rect', point: this.point(values[0], values[1]), size: [values[2], values[3]] }); this.record('roundRect', values); }
  fill(path) { this.record('fill', path ? [{ svg: path.svg }] : []); }
  stroke(path) { this.record('stroke', path ? [{ svg: path.svg }] : []); }
  clip() { this.record('clip'); }
  fillRect(...values) { this.record('fillRect', values); }
  drawImage(...values) { this.record('drawImage', values); }
  // gradients are recorded as the fill style they become (hit sparks)
  createRadialGradient(...args) { return { type: 'radial', args, stops: [], addColorStop(offset, colour) { this.stops.push([offset, colour]); } }; }
  createLinearGradient(...args) { return { type: 'linear', args, stops: [], addColorStop(offset, colour) { this.stops.push([offset, colour]); } }; }
}
export function segments(calls) {
  const result = [];
  for (const c of calls) {
    if (c.op !== 'stroke' || c.alpha <= 0) continue;
    let from;
    for (const p of c.path || []) {
      if (p.op === 'moveTo') from = p.point;
      if (p.op === 'lineTo') { if (from) result.push([...from, ...p.point]); from = p.point; }
    }
  }
  return result;
}
