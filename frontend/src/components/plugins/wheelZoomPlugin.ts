import uPlot from 'uplot';

export default function wheelZoomPlugin(
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
