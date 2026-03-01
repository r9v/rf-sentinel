export type Mode = 'scan' | 'live';

interface Props {
  mode: Mode;
  onChange: (mode: Mode) => void;
}

const MODES: Mode[] = ['scan', 'live'];

const modeBtn = 'flex-1 py-1.5 text-xs font-medium rounded-md transition-all capitalize';
const modeBtnActive = 'bg-cyan-500/20 text-cyan-300 shadow-sm';
const modeBtnLiveActive = 'bg-red-500/20 text-red-300 shadow-sm';
const modeBtnInactive = 'text-gray-400 hover:text-gray-200';

export default function ModeSelector({ mode, onChange }: Props) {
  return (
    <div className="flex gap-1 p-1 bg-gray-800/50 rounded-lg">
      {MODES.map(m => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={`${modeBtn} ${mode === m ? (m === 'live' ? modeBtnLiveActive : modeBtnActive) : modeBtnInactive}`}
        >
          {m === 'live' ? '● LIVE' : m}
        </button>
      ))}
    </div>
  );
}
