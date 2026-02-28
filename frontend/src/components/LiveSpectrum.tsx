import { useRef, useEffect, useCallback } from 'react';

export interface SpectrumFrame {
  freqs_mhz: number[];
  power_db: number[];
  peaks: { freq_mhz: number; power_db: number; bandwidth_khz: number }[];
}

interface Props {
  frame: SpectrumFrame | null;
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

  // Horizontal lines + power labels
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

  // Vertical lines + freq labels
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

function drawMaxHoldTrace(
  ctx: CanvasRenderingContext2D,
  toX: MapFn, toY: MapFn,
  freqs: number[], maxHold: number[],
): void {
  ctx.beginPath();
  ctx.strokeStyle = 'rgba(255,100,50,0.25)';
  ctx.lineWidth = 1;
  for (let i = 0; i < freqs.length; i++) {
    const x = toX(freqs[i]);
    const y = toY(maxHold[i]);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function drawSpectrum(
  ctx: CanvasRenderingContext2D,
  toX: MapFn, toY: MapFn,
  freqs: number[], power: number[], pMin: number,
): void {
  // Fill
  ctx.beginPath();
  ctx.moveTo(toX(freqs[0]), toY(pMin));
  for (let i = 0; i < freqs.length; i++) {
    ctx.lineTo(toX(freqs[i]), toY(power[i]));
  }
  ctx.lineTo(toX(freqs[freqs.length - 1]), toY(pMin));
  ctx.closePath();
  ctx.fillStyle = FILL_COLOR;
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.strokeStyle = LINE_COLOR;
  ctx.lineWidth = 1.5;
  for (let i = 0; i < freqs.length; i++) {
    const x = toX(freqs[i]);
    const y = toY(power[i]);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
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

function drawAxisLabels(
  ctx: CanvasRenderingContext2D,
  ml: number, mt: number, pw: number, ph: number,
  width: number, height: number,
  fMin: number, fMax: number,
  peaks: SpectrumFrame['peaks'],
): void {
  ctx.fillStyle = TEXT_COLOR;
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('Frequency [MHz]', ml + pw / 2, height - 3);

  ctx.save();
  ctx.translate(13, mt + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('Power [dB]', 0, 0);
  ctx.restore();

  // Title
  ctx.fillStyle = '#e0e0e0';
  ctx.font = 'bold 13px sans-serif';
  ctx.textAlign = 'center';
  const title = `LIVE — ${fMin.toFixed(1)}–${fMax.toFixed(1)} MHz`;
  const peakCount = peaks.length > 0 ? `  (${peaks.length} signal${peaks.length !== 1 ? 's' : ''})` : '';
  ctx.fillText(title + peakCount, ml + pw / 2, 18);

  // Live indicator dot
  ctx.fillStyle = '#ff3333';
  ctx.beginPath();
  ctx.arc(ml + 8, 14, 4, 0, Math.PI * 2);
  ctx.fill();
}

export default function LiveSpectrum({ frame, width = 900, height = 320 }: Props) {
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

    const freqs = frame.freqs_mhz;
    const power = frame.power_db;
    const peaks = frame.peaks;

    // Update max hold
    if (!maxHoldRef.current || maxHoldRef.current.length !== power.length) {
      maxHoldRef.current = [...power];
    } else {
      for (let i = 0; i < power.length; i++) {
        if (power[i] > maxHoldRef.current[i]) {
          maxHoldRef.current[i] = power[i];
        } else {
          maxHoldRef.current[i] -= 0.15; // slow decay
        }
      }
    }
    const maxHold = maxHoldRef.current;

    // Axis ranges
    const fMin = freqs[0];
    const fMax = freqs[freqs.length - 1];

    let pMin = Infinity, pMax = -Infinity;
    for (const v of power) {
      if (v < pMin) pMin = v;
      if (v > pMax) pMax = v;
    }
    for (const v of maxHold) {
      if (v > pMax) pMax = v;
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
    drawMaxHoldTrace(ctx, toX, toY, freqs, maxHold);
    drawSpectrum(ctx, toX, toY, freqs, power, pMin);
    drawPeakMarkers(ctx, toX, toY, peaks);
    drawAxisLabels(ctx, ml, mt, pw, ph, width, height, fMin, fMax, peaks);
  }, [frame, width, height]);

  useEffect(() => {
    draw();
  }, [draw]);

  // Reset max hold when frequency range changes
  useEffect(() => {
    maxHoldRef.current = null;
  }, [frame?.freqs_mhz?.[0], frame?.freqs_mhz?.[frame?.freqs_mhz?.length - 1]]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width, height }}
      className="rounded-lg"
    />
  );
}
