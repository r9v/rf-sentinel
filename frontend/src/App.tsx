import { useState, useEffect, useCallback } from 'react';
import { useWebSocket, LogEntry } from './hooks/useWebSocket';
import { getStatus, JobInfo } from './api';
import ControlPanel from './components/ControlPanel';
import LogConsole from './components/LogConsole';
import JobList from './components/JobList';
import ResultView from './components/ResultView';
import LiveSpectrum, { SpectrumFrame } from './components/LiveSpectrum';

const WS_URL = `ws://${window.location.hostname}:8900/api/ws`;

const statusDot = 'w-2 h-2 rounded-full';

// ── Local components ─────────────────────────────────────

function Header({ liveActive, serverOnline }: { liveActive: boolean; serverOnline: boolean }) {
  return (
    <header className="border-b border-gray-800 px-4 py-2.5 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-bold tracking-tight">
          <span className="text-cyan-400">RF</span>Sentinel
        </h1>
        <span className="text-xs text-gray-600 font-mono">v0.1.0</span>
      </div>
      <div className="flex items-center gap-3">
        {liveActive && (
          <span className="text-xs px-2 py-0.5 rounded bg-red-500/15 text-red-300 font-mono animate-pulse">
            ● LIVE
          </span>
        )}
        <div className="flex items-center gap-1.5">
          <span className={`${statusDot} ${serverOnline ? 'bg-green-400' : 'bg-red-400'}`} />
          <span className="text-xs text-gray-500">
            {serverOnline ? 'Server online' : 'Disconnected'}
          </span>
        </div>
      </div>
    </header>
  );
}

function Sidebar({ liveActive, onLiveToggle, selectedJob, onSelectJob }: {
  liveActive: boolean;
  onLiveToggle: (active: boolean) => void;
  selectedJob: JobInfo | null;
  onSelectJob: (job: JobInfo | null) => void;
}) {
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  return (
    <aside className="w-72 border-r border-gray-800 flex flex-col">
      <div className="p-3 border-b border-gray-800/50 flex-shrink-0">
        <ControlPanel
          onJobStarted={() => setRefreshTrigger(n => n + 1)}
          liveActive={liveActive}
          onLiveToggle={onLiveToggle}
        />
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <h3 className="text-xs text-gray-500 uppercase tracking-wider mb-2">Jobs</h3>
        <JobList
          refreshTrigger={refreshTrigger}
          onSelectJob={onSelectJob}
          selectedJobId={selectedJob?.id || null}
        />
      </div>
    </aside>
  );
}

function MainContent({ liveActive, liveFrame, selectedJob, logs, connected, onClear }: {
  liveActive: boolean;
  liveFrame: SpectrumFrame | null;
  selectedJob: JobInfo | null;
  logs: LogEntry[];
  connected: boolean;
  onClear: () => void;
}) {
  return (
    <div className="flex-1 flex flex-col">
      <div className="flex-1 border-b border-gray-800 flex items-center justify-center overflow-hidden">
        {liveActive || liveFrame ? (
          <LiveSpectrum frame={liveFrame} width={900} height={400} />
        ) : (
          <ResultView job={selectedJob} />
        )}
      </div>
      <div className="h-48 flex-shrink-0">
        <LogConsole logs={logs} connected={connected} onClear={onClear} />
      </div>
    </div>
  );
}

// ── App ──────────────────────────────────────────────────

export default function App() {
  const { connected, logs, clearLogs, lastMessage } = useWebSocket(WS_URL);
  const [serverOnline, setServerOnline] = useState(false);
  const [selectedJob, setSelectedJob] = useState<JobInfo | null>(null);
  const [liveActive, setLiveActive] = useState(false);
  const [liveFrame, setLiveFrame] = useState<SpectrumFrame | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        await getStatus();
        setServerOnline(true);
      } catch {
        setServerOnline(false);
      }
    };
    check();
    const interval = setInterval(check, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (lastMessage && lastMessage.type === 'spectrum') {
      setLiveFrame({
        freqs_mhz: lastMessage.freqs_mhz,
        power_db: lastMessage.power_db,
        peaks: lastMessage.peaks,
      });
    }
  }, [lastMessage]);

  const handleLiveToggle = useCallback((active: boolean) => {
    setLiveActive(active);
    if (!active) setLiveFrame(null);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-gray-100">
      <Header liveActive={liveActive} serverOnline={serverOnline} />
      <div className="flex h-[calc(100vh-45px)]">
        <Sidebar
          liveActive={liveActive}
          onLiveToggle={handleLiveToggle}
          selectedJob={selectedJob}
          onSelectJob={setSelectedJob}
        />
        <MainContent
          liveActive={liveActive}
          liveFrame={liveFrame}
          selectedJob={selectedJob}
          logs={logs}
          connected={connected}
          onClear={clearLogs}
        />
      </div>
    </div>
  );
}
