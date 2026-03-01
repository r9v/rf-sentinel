import { useRef, useEffect, useState } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';

export interface SpectrumFrame {
  freqs_mhz: number[];
  power_db: number[];
  peaks: { freq_mhz: number; power_db: number; bandwidth_khz: number }[];
}

interface Props {
  frame: SpectrumFrame | null;
  mode: 'live' | 'scan';
  onPeakClick?: (freq_mhz: number) => void;
}

const BG = '#0a0e1a';
const PLOT_BG = '#0f1525';
const GRID = 'rgba(255,255,255,0.08)';
const AXIS = '#606070';
const LINE = '#00d4ff';
const FILL = 'rgba(0,212,255,0.12)';
const PEAK = '#ff6b35';
const MAX_HOLD_COLOR = 'rgba(255,100,50,0.25)';

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

        ctx.fillStyle = PEAK;
        ctx.font = `bold ${Math.round(9 * dpr)}px monospace`;
        ctx.textAlign = 'center';

        for (const pk of peaks.slice(0, 20)) {
          const x = u.valToPos(pk.freq_mhz, 'x', true);
          const y = u.valToPos(pk.power_db, 'y', true);
          if (x < bbox.left || x > bbox.left + bbox.width) continue;

          const s = 4 * dpr;
          ctx.beginPath();
          ctx.moveTo(x, y - 8 * dpr);
          ctx.lineTo(x - s, y - 2 * dpr);
          ctx.lineTo(x + s, y - 2 * dpr);
          ctx.closePath();
          ctx.fill();
          ctx.fillText(`${pk.freq_mhz.toFixed(3)}`, x, y - 11 * dpr);
        }
        ctx.restore();
      },
    },
  };
}

function wheelZoomPlugin(
  fullRangeRef: React.MutableRefObject<{ xMin: number; xMax: number } | null>,
  factor = 0.75,
): uPlot.Plugin {
  return {
    hooks: {
      ready: (u: uPlot) => {
        const over = u.over;

        over.addEventListener('wheel', (e: WheelEvent) => {
          e.preventDefault();
          const fr = fullRangeRef.current;
          if (!fr) return;
          const { left } = u.cursor;
          if (left == null) return;

          const rect = over.getBoundingClientRect();
          const leftPct = left / rect.width;
          const oxRange = u.scales.x.max! - u.scales.x.min!;
          const nxRange = e.deltaY < 0 ? oxRange * factor : oxRange / factor;
          const xVal = u.posToVal(left, 'x');

          let nxMin = xVal - leftPct * nxRange;
          let nxMax = nxMin + nxRange;

          const fullW = fr.xMax - fr.xMin;
          if (nxRange > fullW) { nxMin = fr.xMin; nxMax = fr.xMax; }
          else if (nxMin < fr.xMin) { nxMin = fr.xMin; nxMax = fr.xMin + nxRange; }
          else if (nxMax > fr.xMax) { nxMax = fr.xMax; nxMin = fr.xMax - nxRange; }

          u.setScale('x', { min: nxMin, max: nxMax });
        });

        over.addEventListener('mousedown', (e: MouseEvent) => {
          if (e.button !== 0) return;
          const fr = fullRangeRef.current;
          if (!fr) return;
          const fullW = fr.xMax - fr.xMin;
          const curW = u.scales.x.max! - u.scales.x.min!;
          if (curW >= fullW * 0.99) return; // not zoomed, skip drag

          e.preventDefault();
          over.style.cursor = 'grabbing';
          const xUnitsPerPx = u.posToVal(1, 'x') - u.posToVal(0, 'x');
          const startX = e.clientX;
          const startMin = u.scales.x.min!;
          const startMax = u.scales.x.max!;

          const onMove = (e: MouseEvent) => {
            const dx = xUnitsPerPx * (e.clientX - startX);
            let nMin = startMin - dx;
            let nMax = startMax - dx;
            if (nMin < fr.xMin) { nMin = fr.xMin; nMax = fr.xMin + curW; }
            if (nMax > fr.xMax) { nMax = fr.xMax; nMin = fr.xMax - curW; }
            u.setScale('x', { min: nMin, max: nMax });
          };
          const onUp = () => {
            over.style.cursor = 'crosshair';
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
          };
          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        });

        over.addEventListener('dblclick', () => {
          const fr = fullRangeRef.current;
          if (fr) u.setScale('x', { min: fr.xMin, max: fr.xMax });
        });
      },
    },
  };
}

function clickPlugin(
  peaksRef: React.MutableRefObject<SpectrumFrame['peaks']>,
  cbRef: React.MutableRefObject<((freq_mhz: number) => void) | undefined>,
): uPlot.Plugin {
  return {
    hooks: {
      ready: (u: uPlot) => {
        const over = u.over;
        over.style.cursor = 'crosshair';

        over.addEventListener('mousemove', (e: MouseEvent) => {
          if (!cbRef.current) return;
          const rect = over.getBoundingClientRect();
          const cx = e.clientX - rect.left;
          const cy = e.clientY - rect.top;
          const near = peaksRef.current.some(pk => {
            const px = u.valToPos(pk.freq_mhz, 'x');
            const py = u.valToPos(pk.power_db, 'y');
            return Math.hypot(px - cx, py - cy) < 15;
          });
          over.style.cursor = near ? 'pointer' : 'crosshair';
        });

        over.addEventListener('click', (e: MouseEvent) => {
          if (!cbRef.current) return;
          const rect = over.getBoundingClientRect();
          const cx = e.clientX - rect.left;
          const cy = e.clientY - rect.top;

          let closest: SpectrumFrame['peaks'][0] | null = null;
          let closestDist = Infinity;
          for (const pk of peaksRef.current) {
            const px = u.valToPos(pk.freq_mhz, 'x');
            const py = u.valToPos(pk.power_db, 'y');
            const dist = Math.hypot(px - cx, py - cy);
            if (dist < 15 && dist < closestDist) {
              closestDist = dist;
              closest = pk;
            }
          }
          if (closest) cbRef.current(closest.freq_mhz);
        });
      },
    },
  };
}

// ── Component ────────────────────────────────────────────

const TITLE_H = 28;

export default function SpectrumChart({
  frame, mode, onPeakClick,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<uPlot | null>(null);
  const peaksRef = useRef<SpectrumFrame['peaks']>([]);
  const maxHoldRef = useRef<number[] | null>(null);
  const fullRangeRef = useRef<{ xMin: number; xMax: number } | null>(null);
  const onPeakClickRef = useRef(onPeakClick);
  onPeakClickRef.current = onPeakClick;
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 400, h: 300 });

  // Measure container
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setSize({ w: Math.floor(width), h: Math.floor(height) - TITLE_H });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Resize existing chart (no destroy/recreate)
  useEffect(() => {
    chartRef.current?.setSize({ width: size.w, height: size.h });
  }, [size]);

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
        y: {},
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
        wheelZoomPlugin(fullRangeRef),
        clickPlugin(peaksRef, onPeakClickRef),
      ],
    };

    const empty: uPlot.AlignedData = mode === 'live'
      ? [[], [], []]
      : [[], []];

    chartRef.current = new uPlot(opts, empty, chartContainerRef.current);

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

    fullRangeRef.current = {
      xMin: freqs_mhz[0],
      xMax: freqs_mhz[freqs_mhz.length - 1],
    };

    // Capture zoom state before setData resets scales
    const fr = fullRangeRef.current;
    const xZoomMin = chart.scales.x.min;
    const xZoomMax = chart.scales.x.max;
    const isZoomed = fr && xZoomMin != null && xZoomMax != null
      && (xZoomMax - xZoomMin) < (fr.xMax - fr.xMin) * 0.99;

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

    // Always reset scales (so y auto-ranges), then restore x zoom
    chart.batch(() => {
      chart.setData(data, true);
      if (isZoomed) {
        chart.setScale('x', { min: xZoomMin!, max: xZoomMax! });
      }
    });
  }, [frame, mode]);

  // Reset max hold when freq range changes
  useEffect(() => {
    maxHoldRef.current = null;
  }, [frame?.freqs_mhz?.[0], frame?.freqs_mhz?.[frame?.freqs_mhz?.length - 1]]);

  const fMin = frame?.freqs_mhz?.[0];
  const fMax = frame?.freqs_mhz?.[frame?.freqs_mhz?.length - 1];
  const peakCount = frame?.peaks?.length ?? 0;

  return (
    <div ref={wrapRef} className="w-full h-full flex flex-col">
      <div className="flex items-center justify-center gap-2 flex-shrink-0" style={{ height: TITLE_H }}>
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
        <span className="text-[10px] text-gray-600 ml-2">scroll to zoom · double-click to reset</span>
      </div>
      <div ref={chartContainerRef} className="flex-1 overflow-hidden rounded-lg" />
    </div>
  );
}
