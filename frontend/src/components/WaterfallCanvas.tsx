import { useRef, useEffect, useState } from 'react';
import type { SpectrumFrame, ChartView } from './SpectrumChart';

interface Props {
  frame?: SpectrumFrame | null;
  view?: ChartView | null;
  resultData?: { freqs_mhz: number[]; power_db: number[][]; duration_s?: number } | null;
  dbRange?: [number, number] | null;
  onDataDbRange?: (min: number, max: number) => void;
}

const TARGET_SECONDS = 60;
const BG_R = 10, BG_G = 14, BG_B = 26;
const BG_U32 = (255 << 24) | (BG_B << 16) | (BG_G << 8) | BG_R;

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

export default function WaterfallCanvas({ frame, view, resultData, dbRange, onDataDbRange }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 400, h: 192 });
  const dbMinRef = useRef(-120);
  const dbMaxRef = useRef(-20);
  const viewRef = useRef<ChartView | null>(null);
  const rowsRef = useRef<Row[]>([]);
  const wfRef = useRef<{ imgData: ImageData; u32: Uint32Array; w: number; h: number } | null>(null);
  const lastDrawRef = useRef(0);

  function getWf(w: number, h: number) {
    const b = wfRef.current;
    if (b && b.w === w && b.h === h) return b;
    const imgData = new ImageData(w, h);
    const u32 = new Uint32Array(imgData.data.buffer);
    u32.fill(BG_U32);
    const wf = { imgData, u32, w, h };
    wfRef.current = wf;
    return wf;
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
    fullRedraw();
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

    const m = getDataMetrics();
    if (!m || m.devH <= 0) return;
    const msPerPx = (TARGET_SECONDS * 1000) / m.devH;
    const elapsed = lastDrawRef.current > 0 ? now - lastDrawRef.current : 0;
    if (elapsed < msPerPx) { if (!lastDrawRef.current) lastDrawRef.current = now; return; }
    const rowH = Math.min(m.devH, Math.max(1, Math.round(elapsed / msPerPx)));
    lastDrawRef.current = now;
    scrollAndDraw(frame.freqs_mhz, frame.power_db, view, rowH);
  }, [frame]);

  useEffect(() => {
    if (!view) return;
    viewRef.current = view;
    lastDrawRef.current = Date.now();
    fullRedraw();
  }, [view?.xStart, view?.xEnd, view?.padLeft, view?.padRight]);

  useEffect(() => {
    if (!resultData?.freqs_mhz.length || !resultData.power_db.length) return;
    renderResult();
  }, [resultData, size, view?.xStart, view?.xEnd, view?.padLeft, view?.padRight, dbRange?.[0], dbRange?.[1]]);

  function renderResult() {
    if (!resultData?.freqs_mhz.length || !resultData.power_db.length) return;
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const devW = cvs.width;
    const devH = cvs.height;
    if (devW <= 0 || devH <= 0) return;

    const { freqs_mhz, power_db } = resultData;
    const nRows = power_db.length;
    const totalTime = resultData.duration_s || nRows * 0.05;
    const xStart = view?.xStart ?? freqs_mhz[0];
    const xEnd = view?.xEnd ?? freqs_mhz[freqs_mhz.length - 1];

    const hasChart = !!view;
    const padLeft = hasChart ? Math.round(view.padLeft * dpr) : Math.round(50 * dpr);
    const padRight = hasChart ? Math.round((view.padRight - 24) * dpr) : Math.round(10 * dpr);
    const padTop = Math.round(5 * dpr);
    const padBottom = Math.round(24 * dpr);
    const dataW = devW - padLeft - padRight;
    const dataH = devH - padTop - padBottom;
    if (dataW <= 0 || dataH <= 0) return;

    let dbMin = Infinity, dbMax = -Infinity;
    for (const row of power_db) {
      for (const v of row) {
        if (v < dbMin) dbMin = v;
        if (v > dbMax) dbMax = v;
      }
    }
    onDataDbRange?.(dbMin, dbMax);
    if (dbRange) {
      dbMinRef.current = dbRange[0];
      dbMaxRef.current = dbRange[1];
    } else {
      dbMinRef.current = dbMin;
      dbMaxRef.current = dbMax;
    }

    const wf = getWf(dataW, dataH);
    wf.u32.fill(BG_U32);
    const stride = dataW * 4;
    for (let dy = 0; dy < dataH; dy++) {
      const ri = Math.min(nRows - 1, Math.floor((dy / dataH) * nRows));
      const strip = renderPixels(dataW, xStart, xEnd, freqs_mhz, power_db[ri]);
      wf.imgData.data.set(strip, dy * stride);
    }

    ctx.fillStyle = '#0a0e1a';
    ctx.fillRect(0, 0, devW, devH);
    ctx.putImageData(wf.imgData, padLeft, padTop);

    const fontSize = Math.round(10 * dpr);
    ctx.font = `${fontSize}px monospace`;
    ctx.fillStyle = '#6b7280';
    ctx.strokeStyle = '#374151';
    ctx.lineWidth = dpr;

    const xTicks = niceTicks(xStart, xEnd, Math.max(2, Math.floor(dataW / (70 * dpr))));
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const freq of xTicks.values) {
      const x = padLeft + ((freq - xStart) / (xEnd - xStart)) * dataW;
      ctx.beginPath();
      ctx.moveTo(x, padTop + dataH);
      ctx.lineTo(x, padTop + dataH + 3 * dpr);
      ctx.stroke();
      ctx.fillText(formatTick(freq, xTicks.step), x, padTop + dataH + 4 * dpr);
    }

    const yTicks = niceTicks(0, totalTime, Math.max(2, Math.floor(dataH / (35 * dpr))));
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (const t of yTicks.values) {
      const y = padTop + (t / totalTime) * dataH;
      ctx.beginPath();
      ctx.moveTo(padLeft - 3 * dpr, y);
      ctx.lineTo(padLeft, y);
      ctx.stroke();
      ctx.fillText(formatTick(t, yTicks.step) + 's', padLeft - 5 * dpr, y);
    }
  }

  function getDataMetrics() {
    const cvs = canvasRef.current;
    if (!cvs) return null;
    const v = viewRef.current;
    if (!v) return null;
    const dpr = window.devicePixelRatio || 1;
    const dataLeft = Math.round(v.padLeft * dpr);
    const dataRight = cvs.width - Math.round(v.padRight * dpr);
    return { dataLeft, dataW: dataRight - dataLeft, devH: cvs.height };
  }

  function scrollAndDraw(freqs: number[], power: number[], v: ChartView, rowH: number) {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext('2d');
    if (!ctx) return;
    const m = getDataMetrics();
    if (!m || m.dataW <= 0 || m.devH <= 0) return;

    const wf = getWf(m.dataW, m.devH);
    const pixels = wf.imgData.data;
    const stride = m.dataW * 4;
    const shift = rowH * stride;

    // Scroll existing data down
    pixels.copyWithin(shift, 0, pixels.length - shift);

    // Render new row strip
    const strip = renderPixels(m.dataW, v.xStart, v.xEnd, freqs, power);
    for (let r = 0; r < rowH; r++) {
      pixels.set(strip, r * stride);
    }

    blit(ctx, wf.imgData, m.dataLeft, m.devH);
  }

  function fullRedraw() {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext('2d');
    if (!ctx) return;
    const v = viewRef.current;
    if (!v) return;
    const m = getDataMetrics();
    if (!m || m.dataW <= 0 || m.devH <= 0) return;

    const rows = rowsRef.current;
    const wf = getWf(m.dataW, m.devH);
    wf.u32.fill(BG_U32);

    if (!rows.length) {
      blit(ctx, wf.imgData, m.dataLeft, m.devH);
      return;
    }

    const now = rows[rows.length - 1].t;
    const spanMs = TARGET_SECONDS * 1000;
    const key = v.xStart * 1e9 + v.xEnd * 1e3 + m.dataW;
    const pixels = wf.imgData.data;
    const stride = m.dataW * 4;

    let ri = rows.length - 1;
    let lastRow: Row | null = null;
    let lastOffset = -1;

    for (let dy = 0; dy < m.devH; dy++) {
      const ageMs = (dy / m.devH) * spanMs;
      const targetT = now - ageMs;

      while (ri > 0 && rows[ri].t > targetT) ri--;
      if (rows[ri].t > targetT) continue;

      const row = rows[ri];

      if (!row.pixels || row.cacheKey !== key) {
        row.pixels = renderPixels(m.dataW, v.xStart, v.xEnd, row.freqs, row.power);
        row.cacheKey = key;
      }

      const offset = dy * stride;
      if (row === lastRow && lastOffset >= 0) {
        pixels.copyWithin(offset, lastOffset, lastOffset + stride);
      } else {
        pixels.set(row.pixels, offset);
      }
      lastRow = row;
      lastOffset = offset;
    }

    blit(ctx, wf.imgData, m.dataLeft, m.devH);
  }

  function blit(ctx: CanvasRenderingContext2D, imgData: ImageData, dataLeft: number, devH: number) {
    ctx.fillStyle = '#0a0e1a';
    ctx.fillRect(0, 0, ctx.canvas.width, devH);
    ctx.putImageData(imgData, dataLeft, 0);
  }

  function renderPixels(w: number, xStart: number, xEnd: number, freqs: number[], power: number[]): Uint8ClampedArray {
    const pixels = new Uint8ClampedArray(w * 4);
    const dbMin = dbMinRef.current;
    const dbSpan = dbMaxRef.current - dbMin;
    if (dbSpan <= 0) return pixels;

    for (let px = 0; px < w; px++) {
      const freq = xStart + (px / w) * (xEnd - xStart);
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

function niceTicks(min: number, max: number, maxTicks: number): { values: number[]; step: number } {
  const range = max - min;
  if (range <= 0 || maxTicks < 2) return { values: [], step: 1 };
  const rawStep = range / maxTicks;
  const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const norm = rawStep / mag;
  let step: number;
  if (norm <= 1.5) step = mag;
  else if (norm <= 3.5) step = 2 * mag;
  else if (norm <= 7.5) step = 5 * mag;
  else step = 10 * mag;
  const values: number[] = [];
  let t = Math.ceil(min / step) * step;
  t = Math.round(t * 1e10) / 1e10;
  while (t <= max + step * 0.001) {
    values.push(t);
    t = Math.round((t + step) * 1e10) / 1e10;
  }
  return { values, step };
}

function formatTick(value: number, step: number): string {
  if (step >= 1) return value.toFixed(0);
  if (step >= 0.1) return value.toFixed(1);
  return value.toFixed(2);
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
