import { useState, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { getStatus, JobInfo } from './api';
import ControlPanel from './components/ControlPanel';
import LogConsole from './components/LogConsole';
import JobList from './components/JobList';
import ResultView from './components/ResultView';

const WS_URL = `ws://${window.location.hostname}:8900/api/ws`;

export default function App() {
  const { connected, logs, clearLogs } = useWebSocket(WS_URL);
  const [demoMode, setDemoMode] = useState(false);
  const [serverOnline, setServerOnline] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [selectedJob, setSelectedJob] = useState<JobInfo | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        const s = await getStatus();
        setServerOnline(true);
        setDemoMode(s.demo_mode);
      } catch {
        setServerOnline(false);
      }
    };
    check();
    const interval = setInterval(check, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleJobStarted = () => {
    setRefreshTrigger(n => n + 1);
  };

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-gray-100">
      {/* Header */}
      <header className="border-b border-gray-800 px-4 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-bold tracking-tight">
            <span className="text-cyan-400">RF</span>Sentinel
          </h1>
          <span className="text-xs text-gray-600 font-mono">v0.1.0</span>
        </div>
        <div className="flex items-center gap-3">
          {demoMode && (
            <span className="text-xs px-2 py-0.5 rounded bg-yellow-500/15 text-yellow-300 font-mono">
              DEMO
            </span>
          )}
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${serverOnline ? 'bg-green-400' : 'bg-red-400'}`} />
            <span className="text-xs text-gray-500">
              {serverOnline ? 'Server online' : 'Disconnected'}
            </span>
          </div>
        </div>
      </header>

      {/* Main layout */}
      <div className="flex h-[calc(100vh-45px)]">
        {/* Left sidebar — controls + jobs */}
        <aside className="w-72 border-r border-gray-800 flex flex-col">
          <div className="p-3 border-b border-gray-800/50 flex-shrink-0">
            <ControlPanel onJobStarted={handleJobStarted} />
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            <h3 className="text-xs text-gray-500 uppercase tracking-wider mb-2">Jobs</h3>
            <JobList
              refreshTrigger={refreshTrigger}
              onSelectJob={setSelectedJob}
              selectedJobId={selectedJob?.id || null}
            />
          </div>
        </aside>

        {/* Main content area */}
        <div className="flex-1 flex flex-col">
          {/* Result view */}
          <div className="flex-1 border-b border-gray-800">
            <ResultView job={selectedJob} />
          </div>

          {/* Console */}
          <div className="h-48 flex-shrink-0">
            <LogConsole logs={logs} connected={connected} onClear={clearLogs} />
          </div>
        </div>
      </div>
    </div>
  );
}
