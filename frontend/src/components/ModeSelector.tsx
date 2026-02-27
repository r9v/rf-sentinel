export type Mode = 'scan' | 'waterfall' | 'live';

interface Props {
  mode: Mode;
  onChange: (mode: Mode) => void;
}

const MODES: Mode[] = ['scan', 'waterfall', 'live'];

export default function ModeSelector({ mode, onChange }: Props) {
  return (
    <div className="flex gap-1 p-1 bg-gray-800/50 rounded-lg">
      {MODES.map(m => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all capitalize
            ${mode === m
              ? m === 'live'
                ? 'bg-red-500/20 text-red-300 shadow-sm'
                : 'bg-cyan-500/20 text-cyan-300 shadow-sm'
              : 'text-gray-400 hover:text-gray-200'
            }`}
        >
          {m === 'live' ? '● LIVE' : m}
        </button>
      ))}
    </div>
  );
}
