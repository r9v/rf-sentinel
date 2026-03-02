import { useRef, useCallback } from 'react';

export interface SliderMarker { pos: number; color: string }

const hThumb = 'absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-cyan-400 cursor-ew-resize hover:bg-cyan-300 z-10';
const vThumb = 'absolute left-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-cyan-400 cursor-ns-resize hover:bg-cyan-300 z-10';

export default function DualRangeSlider({ lo, hi, min, max, onChange, onReset, vertical, snapStep = 0.1, precision = 1, markers }: {
  lo: number; hi: number; min: number; max: number;
  onChange: (lo: number, hi: number) => void;
  onReset: () => void;
  vertical?: boolean;
  snapStep?: number;
  precision?: number;
  markers?: SliderMarker[];
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const valToFrac = (v: number) => max > min ? (v - min) / (max - min) : 0;
  const fracToVal = (f: number) => min + f * (max - min);
  const snap = (v: number) => { const m = 1 / snapStep; return Math.round(v * m) / m; };

  const startDrag = useCallback((mode: 'lo' | 'hi' | 'pan', e: React.MouseEvent) => {
    e.preventDefault();
    const track = trackRef.current;
    if (!track) return;
    const rect = track.getBoundingClientRect();
    const startPos = vertical ? e.clientY : e.clientX;
    const size = vertical ? rect.height : rect.width;
    const startLo = lo;
    const startHi = hi;

    const onMove = (ev: MouseEvent) => {
      const pos = vertical ? ev.clientY : ev.clientX;
      const df = ((pos - startPos) / size) * (vertical ? -1 : 1);
      if (mode === 'lo') {
        onChange(snap(Math.max(min, Math.min(hi - snapStep, fracToVal(valToFrac(startLo) + df)))), hi);
      } else if (mode === 'hi') {
        onChange(lo, snap(Math.max(lo + snapStep, Math.min(max, fracToVal(valToFrac(startHi) + df)))));
      } else {
        const span = startHi - startLo;
        let nLo = fracToVal(valToFrac(startLo) + df);
        let nHi = nLo + span;
        if (nLo < min) { nLo = min; nHi = min + span; }
        if (nHi > max) { nHi = max; nLo = max - span; }
        onChange(snap(nLo), snap(nHi));
      }
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, [lo, hi, min, max, onChange, vertical, snapStep]);

  if (vertical) {
    const hiTop = (1 - valToFrac(hi)) * 100;
    const loTop = (1 - valToFrac(lo)) * 100;
    return (
      <div className="flex flex-col items-center h-full py-1">
        <span className="text-[9px] text-gray-500 font-mono">{hi.toFixed(precision)}</span>
        <div ref={trackRef} className="relative w-3 flex-1 flex justify-center" onDoubleClick={onReset}>
          <div className="absolute inset-y-0 w-1 rounded-full bg-gray-700" />
          {markers?.map((m, i) => {
            const pct = (1 - valToFrac(m.pos)) * 100;
            if (pct < 0 || pct > 100) return null;
            return <div key={i} className="absolute left-0 right-0 pointer-events-none"
              style={{ top: `${pct}%`, height: 2, backgroundColor: m.color }} />;
          })}
          <div
            className="absolute w-1 rounded-full bg-cyan-600/50 cursor-grab active:cursor-grabbing"
            style={{ top: `${hiTop}%`, bottom: `${100 - loTop}%` }}
            onMouseDown={e => startDrag('pan', e)}
          />
          <div className={vThumb} style={{ top: `${hiTop}%` }}
            onMouseDown={e => startDrag('hi', e)} />
          <div className={vThumb} style={{ top: `${loTop}%` }}
            onMouseDown={e => startDrag('lo', e)} />
        </div>
        <span className="text-[9px] text-gray-500 font-mono">{lo.toFixed(precision)}</span>
      </div>
    );
  }

  const loFrac = valToFrac(lo) * 100;
  const hiFrac = valToFrac(hi) * 100;
  return (
    <div ref={trackRef} className="relative w-full h-3 flex items-center" onDoubleClick={onReset}>
      <div className="absolute inset-x-0 h-1 rounded-full bg-gray-700" />
      {markers?.map((m, i) => {
        const pct = valToFrac(m.pos) * 100;
        if (pct < 0 || pct > 100) return null;
        return <div key={i} className="absolute top-0 bottom-0 w-px pointer-events-none"
          style={{ left: `${pct}%`, backgroundColor: m.color }} />;
      })}
      <div
        className="absolute h-1 rounded-full bg-cyan-600/50 cursor-grab active:cursor-grabbing"
        style={{ left: `${loFrac}%`, right: `${100 - hiFrac}%` }}
        onMouseDown={e => startDrag('pan', e)}
      />
      <div className={hThumb} style={{ left: `${loFrac}%` }}
        onMouseDown={e => startDrag('lo', e)} />
      <div className={hThumb} style={{ left: `${hiFrac}%` }}
        onMouseDown={e => startDrag('hi', e)} />
    </div>
  );
}
