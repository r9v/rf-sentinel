const STOPS = [
  [0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99],
  [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164],
];

export function buildLut(): Uint8Array {
  const n = STOPS.length - 1;
  const out = new Uint8Array(256 * 4);
  for (let i = 0; i < 256; i++) {
    const t = (i / 255) * n;
    const idx = Math.min(Math.floor(t), n - 1);
    const f = t - idx;
    const a = STOPS[idx], b = STOPS[idx + 1];
    out[i * 4] = a[0] + (b[0] - a[0]) * f;
    out[i * 4 + 1] = a[1] + (b[1] - a[1]) * f;
    out[i * 4 + 2] = a[2] + (b[2] - a[2]) * f;
    out[i * 4 + 3] = 255;
  }
  return out;
}
