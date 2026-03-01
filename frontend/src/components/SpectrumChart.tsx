import { useRef, useEffect, useCallback } from 'react';

export interface SpectrumFrame {
  freqs_mhz: number[];
  power_db: number[];
  peaks: { freq_mhz: number; power_db: number; bandwidth_khz: number }[];
}

interface Props {
  frame: SpectrumFrame | null;
  mode: 'live' | 'scan';
  width?: number;
  height?: number;
}

const BG = '#0a0e1a';
const GRID_COLOR = 'rgba(255,255,255,0.08)';
const AXIS_COLOR = '#606070';
const LINE_COLOR = '#00d4ff';
const FILL_COLOR = 'rgba(0,212,255,0.12)';
const PEAK_COLOR = '#ff6b35';
const TEXT_COLOR = '#a0a0a0';

type MapFn = (v: number) => number;

function drawGrid(
  ctx: CanvasRenderingContext2D,
  toX: MapFn, toY: MapFn,
  fMin: number, fMax: number,
  pMin: number, pMax: number,
  ml: number, mt: number, pw: number, ph: number,
): void {
  ctx.strokeStyle = GRID_COLOR;
  ctx.lineWidth = 1;

  const pStep = Math.max(5, Math.ceil((pMax - pMin) / 8 / 5) * 5);
  ctx.font = '10px monospace';
  ctx.fillStyle = AXIS_COLOR;
  ctx.textAlign = 'right';
  for (let p = Math.ceil(pMin / pStep) * pStep; p <= pMax; p += pStep) {
    const y = toY(p);
    ctx.beginPath();
    ctx.moveTo(ml, y);
    ctx.lineTo(ml + pw, y);
    ctx.stroke();
    ctx.fillText(`${p}`, ml - 5, y + 3);
  }

  const fRange = fMax - fMin;
  const fStepOptions = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10];
  const fStep = fStepOptions.find(s => fRange / s <= 10) ?? 10;
  ctx.textAlign = 'center';
  for (let f = Math.ceil(fMin / fStep) * fStep; f <= fMax; f += fStep) {
    const x = toX(f);
    ctx.beginPath();
    ctx.moveTo(x, mt);
    ctx.lineTo(x, mt + ph);
    ctx.stroke();
    ctx.fillText(`${f.toFixed(fStep < 0.1 ? 2 : 1)}`, x, mt + ph + 15);
  }
}

function drawTrace(
  ctx: CanvasRenderingContext2D,
  toX: MapFn, toY: MapFn,
  freqs: number[], values: number[],
  stroke: string, lineWidth: number,
): void {
  ctx.beginPath();
  ctx.strokeStyle = stroke;
  ctx.lineWidth = lineWidth;
  for (let i = 0; i < freqs.length; i++) {
    const x = toX(freqs[i]);
    const y = toY(values[i]);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function drawSpectrum(
  ctx: CanvasRenderingContext2D,
  toX: MapFn, toY: MapFn,
  freqs: number[], power: number[], pMin: number,
): void {
  ctx.beginPath();
  ctx.moveTo(toX(freqs[0]), toY(pMin));
  for (let i = 0; i < freqs.length; i++) {
    ctx.lineTo(toX(freqs[i]), toY(power[i]));
  }
  ctx.lineTo(toX(freqs[freqs.length - 1]), toY(pMin));
  ctx.closePath();
  ctx.fillStyle = FILL_COLOR;
  ctx.fill();

  drawTrace(ctx, toX, toY, freqs, power, LINE_COLOR, 1.5);
}

function drawPeakMarkers(
  ctx: CanvasRenderingContext2D,
  toX: MapFn, toY: MapFn,
  peaks: SpectrumFrame['peaks'],
): void {
  ctx.fillStyle = PEAK_COLOR;
  ctx.font = 'bold 9px monospace';
  ctx.textAlign = 'center';
  for (const pk of peaks.slice(0, 20)) {
    const x = toX(pk.freq_mhz);
    const y = toY(pk.power_db);
    ctx.beginPath();
    ctx.moveTo(x, y - 8);
    ctx.lineTo(x - 4, y - 2);
    ctx.lineTo(x + 4, y - 2);
    ctx.closePath();
    ctx.fill();
    ctx.fillText(`${pk.freq_mhz.toFixed(3)}`, x, y - 11);
  }
}

function drawTitle(
  ctx: CanvasRenderingContext2D,
  ml: number, mt: number, pw: number,
  width: number, height: number,
  fMin: number, fMax: number,
  peaks: SpectrumFrame['peaks'],
  mode: 'live' | 'scan',
): void {
  ctx.fillStyle = TEXT_COLOR;
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Frequency [MHz]', ml + pw / 2, height - 3);

  ctx.save();
  ctx.translate(13, mt + (height - mt - 35) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Power [dB]', 0, 0);
  ctx.restore();

  ctx.fillStyle = '#e0e0e0';
  ctx.font = 'bold 13px sans-serif';
  ctx.textAlign = 'center';
  const label = mode === 'live' ? 'LIVE' : 'SCAN';
  const title = `${label} — ${fMin.toFixed(1)}–${fMax.toFixed(1)} MHz`;
  const peakCount = peaks.length > 0 ? `  (${peaks.length} signal${peaks.length !== 1 ? 's' : ''})` : '';
  ctx.fillText(title + peakCount, ml + pw / 2, 18);

  if (mode === 'live') {
    ctx.fillStyle = '#ff3333';
    ctx.beginPath();
    ctx.arc(ml + 8, 14, 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

export default function SpectrumChart({ frame, mode, width = 900, height = 320 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const maxHoldRef = useRef<number[] | null>(null);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !frame || frame.freqs_mhz.length === 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    const { freqs_mhz: freqs, power_db: power, peaks } = frame;

    // Max hold only in live mode
    let maxHold: number[] | null = null;
    if (mode === 'live') {
      if (!maxHoldRef.current || maxHoldRef.current.length !== power.length) {
        maxHoldRef.current = [...power];
      } else {
        for (let i = 0; i < power.length; i++) {
          if (power[i] > maxHoldRef.current[i]) {
            maxHoldRef.current[i] = power[i];
          } else {
            maxHoldRef.current[i] -= 0.15;
          }
        }
      }
      maxHold = maxHoldRef.current;
    }

    const fMin = freqs[0];
    const fMax = freqs[freqs.length - 1];

    let pMin = Infinity, pMax = -Infinity;
    for (const v of power) {
      if (v < pMin) pMin = v;
      if (v > pMax) pMax = v;
    }
    if (maxHold) {
      for (const v of maxHold) {
        if (v > pMax) pMax = v;
      }
    }
    pMin = Math.floor(pMin / 5) * 5 - 5;
    pMax = Math.ceil(pMax / 5) * 5 + 5;

    const ml = 55, mr = 15, mt = 30, mb = 35;
    const pw = width - ml - mr;
    const ph = height - mt - mb;

    const toX = (f: number) => ml + (f - fMin) / (fMax - fMin) * pw;
    const toY = (p: number) => mt + (1 - (p - pMin) / (pMax - pMin)) * ph;

    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#0f1525';
    ctx.fillRect(ml, mt, pw, ph);

    drawGrid(ctx, toX, toY, fMin, fMax, pMin, pMax, ml, mt, pw, ph);
    if (maxHold) drawTrace(ctx, toX, toY, freqs, maxHold, 'rgba(255,100,50,0.25)', 1);
    drawSpectrum(ctx, toX, toY, freqs, power, pMin);
    drawPeakMarkers(ctx, toX, toY, peaks);
    drawTitle(ctx, ml, mt, pw, width, height, fMin, fMax, peaks, mode);
  }, [frame, mode, width, height]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => { maxHoldRef.current = null; },
    [frame?.freqs_mhz?.[0], frame?.freqs_mhz?.[frame?.freqs_mhz?.length - 1]]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width, height }}
      className="rounded-lg"
    />
  );
}
