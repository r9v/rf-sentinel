import uPlot from 'uplot';
import { BG, PLOT_BG } from '../theme';

export default function bgPlugin(): uPlot.Plugin {
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
