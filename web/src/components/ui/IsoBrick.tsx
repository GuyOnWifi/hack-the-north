// Flat-shaded isometric LEGO-style brick drawn as SVG. Used for decoration
// (floating bricks, button glyphs) where a WebGL canvas would be overkill.

type Props = {
  /** Studs along the x axis. */
  w?: number;
  /** Studs along the y axis. */
  d?: number;
  /** Height in plates (3 = a brick). */
  h?: number;
  color?: string;
  /** Round 1x1 plate / tile instead of a box. */
  round?: boolean;
  studs?: boolean;
  size?: number;
  className?: string;
  style?: React.CSSProperties;
};

const C30 = Math.cos(Math.PI / 6);
const S30 = 0.5;
const UNIT = 20; // one stud pitch in SVG units
const PLATE = 8;

function project(x: number, y: number, z: number): [number, number] {
  return [(x - y) * C30, (x + y) * S30 - z];
}

export function shade(hex: string, f: number) {
  const n = parseInt(hex.slice(1), 16);
  const ch = (v: number) => Math.max(0, Math.min(255, Math.round(f >= 0 ? v + (255 - v) * f : v * (1 + f))));
  const r = ch((n >> 16) & 255);
  const g = ch((n >> 8) & 255);
  const b = ch(n & 255);
  return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
}

const pts = (p: [number, number][]) => p.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");

export function IsoBrick({ w = 2, d = 2, h = 3, color = "#d90000", round = false, studs = true, size = 64, className, style }: Props) {
  const X = w * UNIT;
  const Y = d * UNIT;
  const Z = h * PLATE;
  const top = shade(color, 0.12);
  const left = color;
  const right = shade(color, -0.28);
  const studR = UNIT * 0.3;
  const studH = PLATE * 0.55;

  const shapes: React.ReactNode[] = [];

  if (round) {
    const cx = X / 2;
    const cy = Y / 2;
    const r = X / 2;
    const [bx, by] = project(cx, cy, 0);
    const [tx, ty] = project(cx, cy, Z);
    const rx = r * C30 * Math.SQRT2;
    const ry = r * S30 * Math.SQRT2;
    shapes.push(
      <path key="side" d={`M${bx - rx},${by} A${rx},${ry} 0 0 0 ${bx + rx},${by} L${tx + rx},${ty} A${rx},${ry} 0 0 1 ${tx - rx},${ty} Z`} fill={left} />,
      <ellipse key="top" cx={tx} cy={ty} rx={rx} ry={ry} fill={top} />,
    );
    if (studs) shapes.push(...stud(cx, cy, Z, studR * 1.2, studH, color, "s"));
  } else {
    shapes.push(
      <polygon key="l" points={pts([project(0, Y, 0), project(X, Y, 0), project(X, Y, Z), project(0, Y, Z)])} fill={left} />,
      <polygon key="r" points={pts([project(X, 0, 0), project(X, Y, 0), project(X, Y, Z), project(X, 0, Z)])} fill={right} />,
      <polygon key="t" points={pts([project(0, 0, Z), project(X, 0, Z), project(X, Y, Z), project(0, Y, Z)])} fill={top} />,
    );
    if (studs) {
      const list: [number, number][] = [];
      for (let i = 0; i < w; i++) for (let j = 0; j < d; j++) list.push([(i + 0.5) * UNIT, (j + 0.5) * UNIT]);
      list.sort((a, b) => a[0] + a[1] - (b[0] + b[1]));
      list.forEach(([sx, sy], k) => shapes.push(...stud(sx, sy, Z, studR, studH, color, `s${k}`)));
    }
  }

  // Bounding box of the projection, padded for studs.
  const corners = [project(0, 0, 0), project(X, 0, 0), project(0, Y, 0), project(X, Y, 0), project(0, 0, Z + studH), project(X, Y, Z + studH), project(X, 0, Z + studH), project(0, Y, Z + studH)];
  const xs = corners.map((c) => c[0]);
  const ys = corners.map((c) => c[1]);
  const pad = 3;
  const minX = Math.min(...xs) - pad;
  const minY = Math.min(...ys) - pad - studR;
  const vbW = Math.max(...xs) - minX + pad;
  const vbH = Math.max(...ys) - minY + pad;

  return (
    <svg viewBox={`${minX} ${minY} ${vbW} ${vbH}`} width={size} height={(size * vbH) / vbW} className={className} style={style} aria-hidden>
      {shapes}
    </svg>
  );
}

function stud(x: number, y: number, z: number, r: number, h: number, color: string, key: string) {
  const [bx, by] = project(x, y, z);
  const [tx, ty] = project(x, y, z + h);
  const rx = r * C30 * Math.SQRT2;
  const ry = r * S30 * Math.SQRT2;
  return [
    <path key={`${key}a`} d={`M${bx - rx},${by} A${rx},${ry} 0 0 0 ${bx + rx},${by} L${tx + rx},${ty} L${tx - rx},${ty} Z`} fill={shade(color, -0.12)} />,
    <ellipse key={`${key}b`} cx={tx} cy={ty} rx={rx} ry={ry} fill={shade(color, 0.22)} />,
  ];
}

/** The red 2x2 brick glyph used on the yellow "build" buttons. */
export function BrickGlyph({ size = 34 }: { size?: number }) {
  return <IsoBrick w={2} d={1} h={3} color="#d90000" size={size} />;
}
