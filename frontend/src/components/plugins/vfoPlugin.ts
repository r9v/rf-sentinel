import uPlot from 'uplot';
import { VFO_COLOR } from '../theme';

const HIT_PX = 8;
const DRAG_THRESHOLD = 4;

export default function vfoPlugin(
  vfoRef: React.MutableRefObject<number | null>,
  cbRef: React.MutableRefObject<((freq_mhz: number) => void) | undefined>,
  xStartRef: React.MutableRefObject<number>,
  xEndRef: React.MutableRefObject<number>,
  dataXMinRef: React.MutableRefObject<number>,
  dataXMaxRef: React.MutableRefObject<number>,
  setXStart: (v: number) => void,
  setXEnd: (v: number) => void,
): uPlot.Plugin {
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

        over.addEventListener('mousemove', (e: MouseEvent) => {
          if (dragging) return;
          const rect = over.getBoundingClientRect();
          const cx = e.clientX - rect.left;
          if (nearVfo(cx)) { over.style.cursor = 'ew-resize'; return; }
          over.style.cursor = 'crosshair';
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
          if (nearVfo(cx)) return;
          cbRef.current(u.posToVal(cx, 'x'));
        });
      },
    },
  };
}
