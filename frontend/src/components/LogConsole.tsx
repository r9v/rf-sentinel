import { useEffect, useRef } from 'react';
import { LogEntry } from '../hooks/useWebSocket';

interface Props {
  logs: LogEntry[];
  connected: boolean;
  onClear: () => void;
}

export default function LogConsole({ logs, connected, onClear }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700/50">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-gray-400 uppercase tracking-wider">Console</span>
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
        </div>
        <button
          onClick={onClear}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          Clear
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 font-mono text-xs leading-relaxed space-y-0.5">
        {logs.length === 0 && (
          <span className="text-gray-600 italic">Waiting for activity...</span>
        )}
        {logs.map((log, i) => (
          <div
            key={i}
            className={`text-gray-300 ${i === logs.length - 1 ? 'log-new' : ''}`}
          >
            <span className="text-gray-600 mr-2">
              {new Date(log.timestamp).toLocaleTimeString('en-GB')}
            </span>
            {log.job_id && (
              <span className="text-cyan-500/60 mr-1">[{log.job_id.slice(0, 6)}]</span>
            )}
            <span className={log.message.includes('ERROR') ? 'text-red-400' : ''}>
              {log.message}
            </span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
