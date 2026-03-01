import { useState, useEffect, useCallback } from 'react';
import { useWebSocket, LogEntry } from './hooks/useWebSocket';
import { useAudioPlayer } from './hooks/useAudioPlayer';
import { JobInfo, setVfo, toggleAudio } from './api';
import ControlPanel from './components/ControlPanel';
import LogConsole from './components/LogConsole';
import JobList from './components/JobList';
import ResultView from './components/ResultView';
import SpectrumChart, { SpectrumFrame, ChartView } from './components/SpectrumChart';
import WaterfallCanvas from './components/WaterfallCanvas';

const WS_URL = `ws://${window.location.hostname}:8900/api/ws`;
const AUDIO_WS_URL = `ws://${window.location.hostname}:8900/api/ws/audio`;

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
          <span className={`w-2 h-2 rounded-full ${serverOnline ? 'bg-green-400' : 'bg-red-400'}`} />
          <span className="text-xs text-gray-500">
            {serverOnline ? 'Server online' : 'Disconnected'}
          </span>
        </div>
      </div>
    </header>
  );
}

function Sidebar({ liveActive, audioEnabled, onLiveToggle, onAudioToggle, onVolumeChange, vfoFreq, onVfoChange, jobs, selectedJob, onSelectJob }: {
  liveActive: boolean;
  audioEnabled: boolean;
  onLiveToggle: (active: boolean) => void;
  onAudioToggle: (enabled: boolean) => void;
  onVolumeChange: (v: number) => void;
  vfoFreq: number | null;
  onVfoChange: (freq_mhz: number) => void;
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
          vfoFreq={vfoFreq}
          onVfoChange={onVfoChange}
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
  const [chartView, setChartView] = useState<ChartView | null>(null);

  return (
    <div className="flex-1 min-w-0 flex flex-col">
      <div className="flex-1 border-b border-gray-800 overflow-hidden flex flex-col">
        {liveActive || liveFrame ? (
          <>
            <div className="flex-[2] min-h-0">
              <SpectrumChart frame={liveFrame} mode="live" vfoFreq={vfoFreq} onFreqClick={onFreqClick} onViewChange={setChartView} />
            </div>
            <div className="flex-1 min-h-0 border-t border-gray-800/50">
              <WaterfallCanvas frame={liveFrame} view={chartView} />
            </div>
          </>
        ) : (
          <ResultView job={selectedJob} />
        )}
      </div>
      <LogConsole logs={logs} connected={connected} onClear={onClear} />
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
    if (!audioEnabled) {
      toggleAudio({ enabled: true, demod_mode: 'fm' }).catch(() => {});
      setAudioEnabled(true);
      audio.start();
    }
  }, [liveActive, audioEnabled, audio]);

  useEffect(() => {
    if (lastMessage && lastMessage.type === 'spectrum') {
      const freqs: number[] = lastMessage.freqs_mhz;
      setLiveFrame({
        freqs_mhz: freqs,
        power_db: lastMessage.power_db,
        peaks: lastMessage.peaks,
      });
      const center = (freqs[0] + freqs[freqs.length - 1]) / 2;
      setVfoFreq(prev => {
        if (prev != null) {
          if (prev < freqs[0] || prev > freqs[freqs.length - 1]) {
            setAudioEnabled(false);
            audio.stop();
            setVfo(center).catch(() => {});
            return center;
          }
          return prev;
        }
        setVfo(center).catch(() => {});
        return center;
      });
    }
  }, [lastMessage, audio]);

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
          vfoFreq={vfoFreq}
          onVfoChange={handleFreqClick}
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
          vfoFreq={audioEnabled ? vfoFreq : null}
          onFreqClick={handleFreqClick}
        />
      </div>
    </div>
  );
}
