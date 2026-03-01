import { useRef, useEffect, useState } from 'react';
import type { SpectrumFrame, ChartView } from './SpectrumChart';

interface Props {
  frame: SpectrumFrame | null;
  view: ChartView | null;
}

const TARGET_SECONDS = 60;

const LUT = buildLut();
function buildLut(): Uint8Array {
  const stops = [
    [0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99],
    [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164],
  ];
  const n = stops.length - 1;
  const out = new Uint8Array(256 * 4);
  for (let i = 0; i < 256; i++) {
    const t = (i / 255) * n;
    const idx = Math.min(Math.floor(t), n - 1);
    const f = t - idx;
    const a = stops[idx], b = stops[idx + 1];
    out[i * 4] = a[0] + (b[0] - a[0]) * f;
    out[i * 4 + 1] = a[1] + (b[1] - a[1]) * f;
    out[i * 4 + 2] = a[2] + (b[2] - a[2]) * f;
    out[i * 4 + 3] = 255;
  }
  return out;
}

interface Row {
  freqs: number[];
  power: number[];
  t: number;
  pixels: Uint8ClampedArray | null;
  cacheKey: number;
}

export default function WaterfallCanvas({ frame, view }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 400, h: 192 });
  const dbMinRef = useRef(-120);
  const dbMaxRef = useRef(-20);
  const viewRef = useRef<ChartView | null>(null);
  const rowsRef = useRef<Row[]>([]);
  const bufRef = useRef<{ canvas: OffscreenCanvas; ctx: OffscreenCanvasRenderingContext2D; imgData: ImageData; w: number; h: number } | null>(null);

  function getBuf(w: number, h: number) {
    const b = bufRef.current;
    if (b && b.w === w && b.h === h) return b;
    const canvas = new OffscreenCanvas(w, h);
    const ctx = canvas.getContext('2d')!;
    const imgData = ctx.createImageData(w, h);
    const buf = { canvas, ctx, imgData, w, h };
    bufRef.current = buf;
    return buf;
  }

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setSize({ w: Math.floor(width), h: Math.floor(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const dpr = window.devicePixelRatio || 1;
    cvs.width = size.w * dpr;
    cvs.height = size.h * dpr;
    cvs.style.width = `${size.w}px`;
    cvs.style.height = `${size.h}px`;
    redraw();
  }, [size]);

  useEffect(() => {
    if (!frame || !frame.freqs_mhz.length || !view) return;

    const rows = rowsRef.current;
    const now = Date.now();
    rows.push({ freqs: frame.freqs_mhz, power: frame.power_db, t: now, pixels: null, cacheKey: 0 });

    const cutoff = now - TARGET_SECONDS * 1000;
    while (rows.length > 0 && rows[0].t < cutoff) rows.shift();

    let fMin = Infinity, fMax = -Infinity;
    for (let i = 0; i < frame.power_db.length; i++) {
      if (frame.power_db[i] < fMin) fMin = frame.power_db[i];
      if (frame.power_db[i] > fMax) fMax = frame.power_db[i];
    }
    dbMinRef.current += 0.05 * (fMin - dbMinRef.current);
    dbMaxRef.current += 0.05 * (fMax - dbMaxRef.current);

    viewRef.current = view;
    redraw();
  }, [frame]);

  useEffect(() => {
    if (!view) return;
    viewRef.current = view;
    redraw();
  }, [view?.xStart, view?.xEnd, view?.padLeft, view?.padRight]);

  function redraw() {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext('2d');
    if (!ctx) return;
    const v = viewRef.current;
    if (!v) return;

    const dpr = window.devicePixelRatio || 1;
    const dataLeft = Math.round(v.padLeft * dpr);
    const dataRight = cvs.width - Math.round(v.padRight * dpr);
    const dataW = dataRight - dataLeft;
    const pxW = Math.round(dataW / dpr);
    const cssH = Math.round(cvs.height / dpr);

    ctx.fillStyle = '#0a0e1a';
    ctx.fillRect(0, 0, cvs.width, cvs.height);

    const rows = rowsRef.current;
    if (!rows.length || pxW <= 0 || cssH <= 0) return;

    const now = rows[rows.length - 1].t;
    const spanMs = TARGET_SECONDS * 1000;
    const key = v.xStart * 1e9 + v.xEnd * 1e3 + pxW;
    const buf = getBuf(pxW, cssH);
    const pixels = buf.imgData.data;
    pixels.fill(0);

    let ri = rows.length - 1;
    let lastRow: Row | null = null;
    let lastOffset = -1;

    for (let y = 0; y < cssH; y++) {
      const ageMs = (y / cssH) * spanMs;
      const targetT = now - ageMs;

      while (ri > 0 && rows[ri].t > targetT) ri--;
      if (rows[ri].t > targetT) continue;

      const row = rows[ri];
      if (now - row.t > spanMs) continue;

      if (!row.pixels || row.cacheKey !== key) {
        row.pixels = renderPixels(pxW, v.xStart, v.xEnd, row.freqs, row.power);
        row.cacheKey = key;
      }

      const offset = y * pxW * 4;
      if (row === lastRow && lastOffset >= 0) {
        pixels.copyWithin(offset, lastOffset, lastOffset + pxW * 4);
      } else {
        pixels.set(row.pixels, offset);
      }
      lastRow = row;
      lastOffset = offset;
    }

    buf.ctx.putImageData(buf.imgData, 0, 0);
    ctx.drawImage(buf.canvas, 0, 0, pxW, cssH, dataLeft, 0, dataW, cvs.height);
  }

  function renderPixels(pxW: number, xStart: number, xEnd: number, freqs: number[], power: number[]): Uint8ClampedArray {
    const pixels = new Uint8ClampedArray(pxW * 4);
    const dbMin = dbMinRef.current;
    const dbSpan = dbMaxRef.current - dbMin;
    if (dbSpan <= 0) return pixels;

    for (let px = 0; px < pxW; px++) {
      const freq = xStart + (px / pxW) * (xEnd - xStart);
      const db = interpPower(freqs, power, freq);
      const ci = Math.max(0, Math.min(255, Math.round(((db - dbMin) / dbSpan) * 255)));
      pixels[px * 4] = LUT[ci * 4];
      pixels[px * 4 + 1] = LUT[ci * 4 + 1];
      pixels[px * 4 + 2] = LUT[ci * 4 + 2];
      pixels[px * 4 + 3] = 255;
    }
    return pixels;
  }

  return (
    <div ref={wrapRef} className="w-full h-full bg-[#0a0e1a]">
      <canvas ref={canvasRef} className="block" />
    </div>
  );
}

function interpPower(freqs: number[], power: number[], freq: number): number {
  if (freq <= freqs[0]) return power[0];
  if (freq >= freqs[freqs.length - 1]) return power[power.length - 1];
  let lo = 0, hi = freqs.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (freqs[mid] <= freq) lo = mid; else hi = mid;
  }
  const t = (freq - freqs[lo]) / (freqs[hi] - freqs[lo]);
  return power[lo] + t * (power[hi] - power[lo]);
}
