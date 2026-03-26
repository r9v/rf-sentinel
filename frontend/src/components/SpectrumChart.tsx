import { useRef, useEffect, useState, useCallback } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import DualRangeSlider, { SliderMarker } from './DualRangeSlider';
import { GRID, AXIS, LINE, FILL, MAX_HOLD_COLOR, VFO_COLOR } from './theme';
import bgPlugin from './plugins/bgPlugin';
import vfoPlugin from './plugins/vfoPlugin';
import wheelZoomPlugin from './plugins/wheelZoomPlugin';

export interface ChartView {
  xStart: number;
  xEnd: number;
  padLeft: number;
  padRight: number;
}

export interface SpectrumFrame {
  freqs_mhz: number[];
  power_db: number[];
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

const TITLE_H = 28;
const XZOOM_H = 24;
const YZOOM_W = 24;

export default function SpectrumChart({
  frame, mode, vfoFreq, onFreqClick, onViewChange,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<uPlot | null>(null);
  const maxHoldRef = useRef<number[] | null>(null);
  const onFreqClickRef = useRef(onFreqClick);
  onFreqClickRef.current = onFreqClick;
  const onViewChangeRef = useRef(onViewChange);
  onViewChangeRef.current = onViewChange;
  const vfoRef = useRef<number | null>(vfoFreq ?? null);
  vfoRef.current = vfoFreq ?? null;
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
        vfoPlugin(vfoRef, onFreqClickRef, xStartRef, xEndRef, dataXMinRef, dataXMaxRef, setXStart, setXEnd),
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

    const { freqs_mhz, power_db } = frame;

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

  useEffect(() => {
    chartRef.current?.redraw(false);
  }, []);

  const fMin = frame?.freqs_mhz?.[0];
  const fMax = frame?.freqs_mhz?.[frame?.freqs_mhz?.length - 1];

  const xSliderMarkers: SliderMarker[] = [];
  if (vfoFreq != null) {
    xSliderMarkers.push({ pos: vfoFreq, color: VFO_COLOR });
  }

  const ySliderMarkers: SliderMarker[] = [];
  if (dbRangeRef.current) {
    ySliderMarkers.push({ pos: dbRangeRef.current.min, color: '#ff6b35' });
    ySliderMarkers.push({ pos: dbRangeRef.current.max, color: '#ff6b35' });
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
