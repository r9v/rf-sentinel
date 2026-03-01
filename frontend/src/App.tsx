import { useState, useEffect, useCallback } from 'react';
import { useWebSocket, LogEntry } from './hooks/useWebSocket';
import { useAudioPlayer } from './hooks/useAudioPlayer';
import { JobInfo, setVfo } from './api';
import ControlPanel from './components/ControlPanel';
import LogConsole from './components/LogConsole';
import JobList from './components/JobList';
import ResultView from './components/ResultView';
import SpectrumChart, { SpectrumFrame } from './components/SpectrumChart';

const WS_URL = `ws://${window.location.hostname}:8900/api/ws`;
const AUDIO_WS_URL = `ws://${window.location.hostname}:8900/api/ws/audio`;

const statusDot = 'w-2 h-2 rounded-full';

// ── Local components ─────────────────────────────────────

function Header({ liveActive, audioEnabled, serverOnline }: {
  liveActive: boolean; audioEnabled: boolean; serverOnline: boolean;
}) {
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
        {audioEnabled && (
          <span className="text-xs px-2 py-0.5 rounded bg-green-500/15 text-green-300 font-mono">
            🔊 AUDIO
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

function Sidebar({ liveActive, audioEnabled, onLiveToggle, onAudioToggle, onVolumeChange, jobs, selectedJob, onSelectJob }: {
  liveActive: boolean;
  audioEnabled: boolean;
  onLiveToggle: (active: boolean) => void;
  onAudioToggle: (enabled: boolean) => void;
  onVolumeChange: (v: number) => void;
  jobs: JobInfo[];
  selectedJob: JobInfo | null;
  onSelectJob: (job: JobInfo | null) => void;
}) {
  return (
    <aside className="w-72 border-r border-gray-800 flex flex-col">
      <div className="p-3 border-b border-gray-800/50 flex-shrink-0">
        <ControlPanel
          liveActive={liveActive}
          onLiveToggle={onLiveToggle}
          audioEnabled={audioEnabled}
          onAudioToggle={onAudioToggle}
          onVolumeChange={onVolumeChange}
        />
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <h3 className="text-xs text-gray-500 uppercase tracking-wider mb-2">Jobs</h3>
        <JobList
          jobs={jobs}
          onSelectJob={onSelectJob}
          selectedJobId={selectedJob?.id || null}
        />
      </div>
    </aside>
  );
}

function MainContent({ liveActive, liveFrame, selectedJob, logs, connected, onClear, vfoFreq, onFreqClick }: {
  liveActive: boolean;
  liveFrame: SpectrumFrame | null;
  selectedJob: JobInfo | null;
  logs: LogEntry[];
  connected: boolean;
  onClear: () => void;
  vfoFreq: number | null;
  onFreqClick: (freq_mhz: number) => void;
}) {
  return (
    <div className="flex-1 min-w-0 flex flex-col">
      <div className="flex-1 border-b border-gray-800 flex items-center justify-center overflow-hidden">
        {liveActive || liveFrame ? (
          <SpectrumChart frame={liveFrame} mode="live" vfoFreq={vfoFreq} onFreqClick={onFreqClick} />
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
  const audio = useAudioPlayer(AUDIO_WS_URL);
  const { connected, logs, clearLogs, lastMessage, jobs } = useWebSocket(WS_URL);
  const [selectedJob, setSelectedJob] = useState<JobInfo | null>(null);
  const [liveActive, setLiveActive] = useState(false);
  const [liveFrame, setLiveFrame] = useState<SpectrumFrame | null>(null);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [vfoFreq, setVfoFreq] = useState<number | null>(null);

  const handleFreqClick = useCallback((freq_mhz: number) => {
    if (!liveActive) return;
    setVfoFreq(freq_mhz);
    setVfo(freq_mhz).catch(() => {});
  }, [liveActive]);

  useEffect(() => {
    if (lastMessage && lastMessage.type === 'spectrum') {
      const freqs: number[] = lastMessage.freqs_mhz;
      setLiveFrame({
        freqs_mhz: freqs,
        power_db: lastMessage.power_db,
        peaks: lastMessage.peaks,
      });
      setVfoFreq(prev => {
        if (prev != null) return prev;
        const center = (freqs[0] + freqs[freqs.length - 1]) / 2;
        setVfo(center).catch(() => {});
        return center;
      });
    }
  }, [lastMessage]);

  const handleLiveToggle = useCallback((active: boolean) => {
    setLiveActive(active);
    if (!active) {
      setLiveFrame(null);
      setAudioEnabled(false);
      setVfoFreq(null);
      audio.stop();
    }
  }, [audio]);

  const handleAudioToggle = useCallback((enabled: boolean) => {
    setAudioEnabled(enabled);
    if (enabled) {
      audio.start();
    } else {
      audio.stop();
    }
  }, [audio]);

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-gray-100">
      <Header liveActive={liveActive} audioEnabled={audioEnabled} serverOnline={connected} />
      <div className="flex h-[calc(100vh-45px)]">
        <Sidebar
          liveActive={liveActive}
          audioEnabled={audioEnabled}
          onLiveToggle={handleLiveToggle}
          onAudioToggle={handleAudioToggle}
          onVolumeChange={audio.setVolume}
          jobs={jobs}
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
          vfoFreq={vfoFreq}
          onFreqClick={handleFreqClick}
        />
      </div>
    </div>
  );
}
