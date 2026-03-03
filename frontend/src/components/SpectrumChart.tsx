import { useRef, useEffect, useState, useCallback } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import DualRangeSlider, { SliderMarker } from './DualRangeSlider';

export interface ChartView {
  xStart: number;
  xEnd: number;
  padLeft: number;
  padRight: number;
}

export interface SpectrumFrame {
  freqs_mhz: number[];
  power_db: number[];
  peaks: { freq_mhz: number; power_db: number; bandwidth_khz: number; signal_type?: string; duty_cycle?: number; transient?: boolean }[];
}

interface Props {
  frame: SpectrumFrame | null;
  mode: 'live' | 'scan';
  vfoFreq?: number | null;
  onFreqClick?: (freq_mhz: number) => void;
  onViewChange?: (view: ChartView) => void;
}

function useStateRef<T>(init: T): [T, (v: T) => void, React.MutableRefObject<T>] {
  const [val, setVal] = useState(init);
  const ref = useRef(val);
  ref.current = val;
  return [val, setVal, ref];
}

const BG = '#0a0e1a';
const PLOT_BG = '#0f1525';
const GRID = 'rgba(255,255,255,0.08)';
const AXIS = '#606070';
const LINE = '#00d4ff';
const FILL = 'rgba(0,212,255,0.12)';
const PEAK = '#ff6b35';
const MAX_HOLD_COLOR = 'rgba(255,100,50,0.25)';
const VFO_COLOR = '#44ff44';

export const TYPE_COLORS: Record<string, string> = {
  fm_broadcast: '#ff6b35',
  narrowband_fm: '#44aaff',
  digital: '#ff44ff',
  am_broadcast: '#44ff88',
  carrier: '#ffdd44',
  aviation: '#00e5ff',
  ham: '#76ff03',
  ism: '#e040fb',
  gsm: '#ff5252',
  adsb: '#40c4ff',
};
export const TYPE_LABELS: Record<string, string> = {
  fm_broadcast: 'FM',
  narrowband_fm: 'NFM',
  digital: 'DIG',
  am_broadcast: 'AM',
  carrier: 'CW',
  aviation: 'AIR',
  ham: 'HAM',
  ism: 'ISM',
  gsm: 'GSM',
  adsb: 'ADS',
};

// ── Plugins ──────────────────────────────────────────────

function bgPlugin(): uPlot.Plugin {
  return {
    hooks: {
      drawClear: (u: uPlot) => {
        const { ctx } = u;
        const cw = ctx.canvas.width;
        const ch = ctx.canvas.height;
        ctx.save();
        ctx.fillStyle = BG;
        ctx.fillRect(0, 0, cw, ch);
        const { left, top, width, height } = u.bbox;
        ctx.fillStyle = PLOT_BG;
        ctx.fillRect(left, top, width, height);
        ctx.restore();
      },
    },
  };
}

function peakMarkersPlugin(
  peaksRef: React.MutableRefObject<SpectrumFrame['peaks']>,
): uPlot.Plugin {
  return {
    hooks: {
      draw: (u: uPlot) => {
        const peaks = peaksRef.current;
        if (!peaks.length) return;

        const { ctx, bbox } = u;
        const dpr = uPlot.pxRatio;
        ctx.save();
        ctx.beginPath();
        ctx.rect(bbox.left, bbox.top, bbox.width, bbox.height);
        ctx.clip();

        ctx.font = `bold ${Math.round(9 * dpr)}px monospace`;
        ctx.textAlign = 'center';

        const visible = peaks.filter(pk => {
          const x = u.valToPos(pk.freq_mhz, 'x', true);
          return x >= bbox.left && x <= bbox.left + bbox.width;
        });
        const labelGap = 50 * dpr;
        let lastLabelX = -Infinity;
        for (const pk of visible) {
          const x = u.valToPos(pk.freq_mhz, 'x', true);
          const color = (pk.signal_type && TYPE_COLORS[pk.signal_type]) || '#888888';
          ctx.fillStyle = color;

          const s = 4 * dpr;
          let markerY: number;
          if (pk.transient) {
            const freqs = u.data[0] as number[];
            const psd = u.data[1] as number[];
            let psdDb = pk.power_db;
            if (freqs.length > 1) {
              const step = freqs[1] - freqs[0];
              const idx = Math.round((pk.freq_mhz - freqs[0]) / step);
              if (idx >= 0 && idx < psd.length) psdDb = psd[idx];
            }
            markerY = u.valToPos(psdDb, 'y', true);
            ctx.beginPath();
            ctx.arc(x, markerY - 5 * dpr, s, 0, Math.PI * 2);
            ctx.fill();
          } else {
            markerY = u.valToPos(pk.power_db, 'y', true);
            ctx.beginPath();
            ctx.moveTo(x, markerY - 8 * dpr);
            ctx.lineTo(x - s, markerY - 2 * dpr);
            ctx.lineTo(x + s, markerY - 2 * dpr);
            ctx.closePath();
            ctx.fill();
          }

          if (x - lastLabelX >= labelGap) {
            lastLabelX = x;
            const label = pk.signal_type ? TYPE_LABELS[pk.signal_type] : undefined;
            ctx.fillText(`${pk.freq_mhz.toFixed(3)}`, x, markerY - 11 * dpr);
            if (label) {
              ctx.fillText(label, x, markerY - 20 * dpr);
            }
          }
        }
        ctx.restore();
      },
    },
  };
}

function vfoPlugin(
  vfoRef: React.MutableRefObject<number | null>,
  cbRef: React.MutableRefObject<((freq_mhz: number) => void) | undefined>,
  xStartRef: React.MutableRefObject<number>,
  xEndRef: React.MutableRefObject<number>,
  dataXMinRef: React.MutableRefObject<number>,
  dataXMaxRef: React.MutableRefObject<number>,
  setXStart: (v: number) => void,
  setXEnd: (v: number) => void,
  peaksRef: React.MutableRefObject<SpectrumFrame['peaks']>,
  modeRef: React.MutableRefObject<string>,
): uPlot.Plugin {
  const HIT_PX = 8;
  const PEAK_HIT_PX = 12;
  const DRAG_THRESHOLD = 4;
  let dragging: 'vfo' | 'pan' | false = false;
  let suppressClick = false;

  return {
    hooks: {
      draw: (u: uPlot) => {
        const freq = vfoRef.current;
        if (freq == null) return;
        const { ctx, bbox } = u;
        const dpr = uPlot.pxRatio;
        const x = u.valToPos(freq, 'x', true);
        if (x < bbox.left || x > bbox.left + bbox.width) return;

        ctx.save();
        ctx.beginPath();
        ctx.rect(bbox.left, bbox.top, bbox.width, bbox.height);
        ctx.clip();

        ctx.strokeStyle = VFO_COLOR;
        ctx.lineWidth = 1.5 * dpr;
        ctx.setLineDash([4 * dpr, 3 * dpr]);
        ctx.beginPath();
        ctx.moveTo(x, bbox.top);
        ctx.lineTo(x, bbox.top + bbox.height);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = VFO_COLOR;
        ctx.font = `bold ${Math.round(9 * dpr)}px monospace`;
        ctx.textAlign = 'center';
        ctx.fillText(`▼ ${freq.toFixed(3)}`, x, bbox.top + 12 * dpr);

        ctx.restore();
      },

      ready: (u: uPlot) => {
        const over = u.over;
        over.style.cursor = 'crosshair';

        const nearVfo = (cx: number) => {
          if (vfoRef.current == null) return false;
          const vx = u.valToPos(vfoRef.current, 'x');
          return Math.abs(cx - vx) < HIT_PX;
        };

        const nearPeak = (cx: number, cy: number) => {
          let bestPk: SpectrumFrame['peaks'][0] | null = null;
          let bestDist = PEAK_HIT_PX;
          for (const pk of peaksRef.current) {
            const px = u.valToPos(pk.freq_mhz, 'x');
            const py = u.valToPos(pk.power_db, 'y');
            const dist = Math.hypot(cx - px, cy - py);
            if (dist < bestDist) { bestDist = dist; bestPk = pk; }
          }
          return bestPk;
        };

        over.addEventListener('mousemove', (e: MouseEvent) => {
          if (dragging) return;
          const rect = over.getBoundingClientRect();
          const cx = e.clientX - rect.left;
          const cy = e.clientY - rect.top;
          if (nearVfo(cx)) { over.style.cursor = 'ew-resize'; return; }
          if (modeRef.current === 'scan' && cbRef.current) {
            over.style.cursor = nearPeak(cx, cy) ? 'pointer' : 'crosshair';
          } else {
            over.style.cursor = 'crosshair';
          }
        });

        over.addEventListener('mousedown', (e: MouseEvent) => {
          const rect = over.getBoundingClientRect();
          const cx = e.clientX - rect.left;
          e.preventDefault();
          suppressClick = false;

          if (nearVfo(cx) && cbRef.current) {
            dragging = 'vfo';
            over.style.cursor = 'ew-resize';
            const onMove = (ev: MouseEvent) => {
              const mx = ev.clientX - rect.left;
              cbRef.current?.(u.posToVal(mx, 'x'));
            };
            const onUp = () => {
              dragging = false;
              suppressClick = true;
              document.removeEventListener('mousemove', onMove);
              document.removeEventListener('mouseup', onUp);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
            return;
          }

          const startX = e.clientX;
          const startLo = xStartRef.current;
          const startHi = xEndRef.current;
          let moved = false;

          const onMove = (ev: MouseEvent) => {
            const dx = ev.clientX - startX;
            if (!moved && Math.abs(dx) < DRAG_THRESHOLD) return;
            if (!moved) {
              moved = true;
              dragging = 'pan';
              over.style.cursor = 'grabbing';
            }
            const freqPerPx = (startHi - startLo) / over.clientWidth;
            const dFreq = -dx * freqPerPx;
            let nLo = startLo + dFreq;
            let nHi = startHi + dFreq;
            const dMin = dataXMinRef.current;
            const dMax = dataXMaxRef.current;
            if (nLo < dMin) { nHi += dMin - nLo; nLo = dMin; }
            if (nHi > dMax) { nLo -= nHi - dMax; nHi = dMax; }
            setXStart(nLo);
            setXEnd(nHi);
          };
          const onUp = () => {
            if (moved) suppressClick = true;
            dragging = false;
            over.style.cursor = 'crosshair';
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
          };
          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        });

        over.addEventListener('click', (e: MouseEvent) => {
          if (!cbRef.current || suppressClick) { suppressClick = false; return; }
          const rect = over.getBoundingClientRect();
          const cx = e.clientX - rect.left;
          const cy = e.clientY - rect.top;
          if (nearVfo(cx)) return;
          if (modeRef.current === 'scan') {
            const pk = nearPeak(cx, cy);
            if (pk) cbRef.current(pk.freq_mhz);
          } else {
            cbRef.current(u.posToVal(cx, 'x'));
          }
        });
      },
    },
  };
}

function wheelZoomPlugin(
  xStartRef: React.MutableRefObject<number>,
  xEndRef: React.MutableRefObject<number>,
  dataXMinRef: React.MutableRefObject<number>,
  dataXMaxRef: React.MutableRefObject<number>,
  setXStart: (v: number) => void,
  setXEnd: (v: number) => void,
): uPlot.Plugin {
  return {
    hooks: {
      ready: (u: uPlot) => {
        u.over.addEventListener('wheel', (e: WheelEvent) => {
          e.preventDefault();
          const rect = u.over.getBoundingClientRect();
          const cx = e.clientX - rect.left;
          const cursorFreq = u.posToVal(cx, 'x');

          const lo = xStartRef.current;
          const hi = xEndRef.current;
          const span = hi - lo;
          const minSpan = 0.1;
          const factor = e.deltaY > 0 ? 1.25 : 0.8;
          const newSpan = Math.max(minSpan, span * factor);

          const frac = (cursorFreq - lo) / span;
          let nLo = cursorFreq - frac * newSpan;
          let nHi = cursorFreq + (1 - frac) * newSpan;

          const dMin = dataXMinRef.current;
          const dMax = dataXMaxRef.current;
          if (nLo < dMin) { nLo = dMin; nHi = dMin + newSpan; }
          if (nHi > dMax) { nHi = dMax; nLo = dMax - newSpan; }
          nLo = Math.max(dMin, nLo);
          nHi = Math.min(dMax, nHi);

          setXStart(nLo);
          setXEnd(nHi);
        }, { passive: false });
      },
    },
  };
}

// ── Component ────────────────────────────────────────────

const TITLE_H = 28;
const XZOOM_H = 24;
const YZOOM_W = 24;

export default function SpectrumChart({
  frame, mode, vfoFreq, onFreqClick, onViewChange,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<uPlot | null>(null);
  const peaksRef = useRef<SpectrumFrame['peaks']>([]);
  const maxHoldRef = useRef<number[] | null>(null);
  const onFreqClickRef = useRef(onFreqClick);
  onFreqClickRef.current = onFreqClick;
  const onViewChangeRef = useRef(onViewChange);
  onViewChangeRef.current = onViewChange;
  const vfoRef = useRef<number | null>(vfoFreq ?? null);
  vfoRef.current = vfoFreq ?? null;
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 400, h: 300 });
  const [yLo, setYLo, yLoRef] = useStateRef(-150);
  const [yHi, setYHi, yHiRef] = useStateRef(0);
  const [dataXMin, setDataXMin, dataXMinRef] = useStateRef(24);
  const [dataXMax, setDataXMax, dataXMaxRef] = useStateRef(1766);
  const [xStart, setXStart, xStartRef] = useStateRef(24);
  const [xEnd, setXEnd, xEndRef] = useStateRef(1766);
  const prevDataRange = useRef('');
  const dbHistoryRef = useRef<{ min: number; max: number; t: number }[]>([]);
  const dbRangeRef = useRef<{ min: number; max: number } | null>(null);
  const [plotPad, setPlotPad] = useState({ left: 0, right: 0 });
  const syncPlotPad = useCallback(() => {
    const c = chartRef.current;
    if (!c) return;
    const dpr = uPlot.pxRatio;
    const left = Math.round(c.bbox.left / dpr);
    const right = Math.round(size.w - (c.bbox.left + c.bbox.width) / dpr);
    setPlotPad(p => (p.left === left && p.right === right) ? p : { left, right });
  }, [size.w]);

  // Measure container
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setSize({ w: Math.floor(width) - YZOOM_W, h: Math.floor(height) - TITLE_H - XZOOM_H });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Resize existing chart (no destroy/recreate)
  useEffect(() => {
    chartRef.current?.setSize({ width: size.w, height: size.h });
    syncPlotPad();
  }, [size, syncPlotPad]);

  // Create / recreate chart when mode changes
  useEffect(() => {
    if (!chartContainerRef.current) return;

    chartRef.current?.destroy();
    chartRef.current = null;
    maxHoldRef.current = null;

    const series: uPlot.Series[] = [
      {},
      {
        label: 'Power',
        stroke: LINE,
        width: 1.5,
        fill: FILL,
      },
    ];
    if (mode === 'live') {
      series.push({
        label: 'Max Hold',
        stroke: MAX_HOLD_COLOR,
        width: 1,
      });
    }

    const axisFont = '10px monospace';
    const labelFont = '11px sans-serif';

    const opts: uPlot.Options = {
      width: size.w,
      height: size.h,
      pxAlign: 0,
      scales: {
        x: { time: false },
        y: { auto: false },
      },
      axes: [
        {
          stroke: AXIS,
          grid: { stroke: GRID, width: 1 },
          ticks: { stroke: GRID, width: 1 },
          gap: 6,
          size: 30,
          font: axisFont,
          labelFont,
          label: 'Frequency [MHz]',
          labelSize: 16,
          labelGap: 2,
        },
        {
          stroke: AXIS,
          grid: { stroke: GRID, width: 1 },
          ticks: { stroke: GRID, width: 1 },
          gap: 6,
          size: 45,
          font: axisFont,
          labelFont,
          label: 'Power [dB]',
          labelSize: 16,
          labelGap: 2,
        },
      ],
      series,
      cursor: {
        drag: { setScale: false },
        points: { show: false },
      },
      select: { show: false, left: 0, top: 0, width: 0, height: 0 },
      legend: { show: false },
      plugins: [
        bgPlugin(),
        peakMarkersPlugin(peaksRef),
        vfoPlugin(vfoRef, onFreqClickRef, xStartRef, xEndRef, dataXMinRef, dataXMaxRef, setXStart, setXEnd, peaksRef, modeRef),
        wheelZoomPlugin(xStartRef, xEndRef, dataXMinRef, dataXMaxRef, setXStart, setXEnd),
      ],
    };

    const empty: uPlot.AlignedData = mode === 'live'
      ? [[], [], []]
      : [[], []];

    chartRef.current = new uPlot(opts, empty, chartContainerRef.current);
    syncPlotPad();

    return () => {
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, [mode]);

  // Push data on each frame
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !frame || !frame.freqs_mhz.length) return;

    const { freqs_mhz, power_db, peaks } = frame;
    peaksRef.current = peaks;

    let fMin = Infinity, fMax = -Infinity;
    for (let i = 0; i < power_db.length; i++) {
      if (power_db[i] < fMin) fMin = power_db[i];
      if (power_db[i] > fMax) fMax = power_db[i];
    }
    const now = Date.now();
    const hist = dbHistoryRef.current;
    hist.push({ min: fMin, max: fMax, t: now });
    const cutoff = now - 30_000;
    while (hist.length > 0 && hist[0].t < cutoff) hist.shift();
    let wMin = Infinity, wMax = -Infinity;
    for (const h of hist) {
      if (h.min < wMin) wMin = h.min;
      if (h.max > wMax) wMax = h.max;
    }
    dbRangeRef.current = { min: Math.floor(wMin), max: Math.ceil(wMax) };

    const rangeKey = `${freqs_mhz[0]}:${freqs_mhz[freqs_mhz.length - 1]}`;
    if (rangeKey !== prevDataRange.current) {
      prevDataRange.current = rangeKey;
      setDataXMin(freqs_mhz[0]);
      setDataXMax(freqs_mhz[freqs_mhz.length - 1]);
      setXStart(freqs_mhz[0]);
      setXEnd(freqs_mhz[freqs_mhz.length - 1]);
      xStartRef.current = freqs_mhz[0];
      xEndRef.current = freqs_mhz[freqs_mhz.length - 1];
      const pad = mode === 'live' ? 10 : 5;
      setYLo(Math.floor(fMin - pad));
      setYHi(Math.ceil(fMax + pad));
      dbHistoryRef.current = [];
    }

    let data: uPlot.AlignedData;
    if (mode === 'live') {
      if (!maxHoldRef.current || maxHoldRef.current.length !== power_db.length) {
        maxHoldRef.current = [...power_db];
      } else {
        for (let i = 0; i < power_db.length; i++) {
          if (power_db[i] > maxHoldRef.current[i]) {
            maxHoldRef.current[i] = power_db[i];
          } else {
            maxHoldRef.current[i] -= 0.15;
          }
        }
      }
      data = [freqs_mhz, power_db, [...maxHoldRef.current]];
    } else {
      data = [freqs_mhz, power_db];
    }

    chart.batch(() => {
      chart.setData(data, true);
      chart.setScale('x', { min: xStartRef.current, max: xEndRef.current });
      chart.setScale('y', { min: yLoRef.current, max: yHiRef.current });
    });
  }, [frame, mode]);

  // Reset max hold when freq range changes
  useEffect(() => {
    maxHoldRef.current = null;
  }, [frame?.freqs_mhz?.[0], frame?.freqs_mhz?.[frame?.freqs_mhz?.length - 1]]);

  useEffect(() => {
    chartRef.current?.setScale('y', { min: yLo, max: yHi });
  }, [yLo, yHi]);

  useEffect(() => {
    chartRef.current?.setScale('x', { min: xStart, max: xEnd });
    onViewChangeRef.current?.({ xStart, xEnd, padLeft: plotPad.left, padRight: plotPad.right + YZOOM_W });
  }, [xStart, xEnd, plotPad.left, plotPad.right]);

  useEffect(() => {
    chartRef.current?.redraw(false);
  }, [vfoFreq]);

  const fMin = frame?.freqs_mhz?.[0];
  const fMax = frame?.freqs_mhz?.[frame?.freqs_mhz?.length - 1];
  const peakCount = frame?.peaks?.length ?? 0;

  const xSliderMarkers: SliderMarker[] = [];
  if (frame?.peaks) {
    for (const pk of frame.peaks) {
      xSliderMarkers.push({ pos: pk.freq_mhz, color: PEAK });
    }
  }
  if (vfoFreq != null) {
    xSliderMarkers.push({ pos: vfoFreq, color: VFO_COLOR });
  }

  const ySliderMarkers: SliderMarker[] = [];
  if (dbRangeRef.current) {
    ySliderMarkers.push({ pos: dbRangeRef.current.min, color: PEAK });
    ySliderMarkers.push({ pos: dbRangeRef.current.max, color: PEAK });
  }

  return (
    <div ref={wrapRef} className="w-full h-full flex flex-col">
      <div className="flex items-center px-3 flex-shrink-0" style={{ height: TITLE_H }}>
        <div className="flex items-center gap-2">
          {mode === 'live' && (
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          )}
          <span className="text-sm font-bold text-gray-200">
            {mode === 'live' ? 'LIVE' : 'SCAN'}
            {fMin != null && fMax != null && ` — ${fMin.toFixed(1)}–${fMax.toFixed(1)} MHz`}
          </span>
          {peakCount > 0 && (
            <span className="text-xs text-gray-500">
              ({peakCount} signal{peakCount !== 1 ? 's' : ''})
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-shrink-0" style={{ height: XZOOM_H, paddingLeft: plotPad.left, paddingRight: plotPad.right }}>
            <DualRangeSlider lo={xStart} hi={xEnd} min={dataXMin} max={dataXMax}
              markers={xSliderMarkers}
              onChange={(lo, hi) => { setXStart(lo); setXEnd(hi); }}
              onReset={() => { setXStart(dataXMin); setXEnd(dataXMax); }} />
          </div>
          <div ref={chartContainerRef} className="flex-1 overflow-hidden rounded-lg" />
        </div>
        <div className="flex-shrink-0" style={{ width: YZOOM_W }}>
          <DualRangeSlider lo={yLo} hi={yHi} min={-150} max={0} vertical
            snapStep={1} precision={0} markers={ySliderMarkers}
            onChange={(lo, hi) => { setYLo(lo); setYHi(hi); }}
            onReset={() => { setYLo(-150); setYHi(0); }} />
        </div>
      </div>
    </div>
  );
}
