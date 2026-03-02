import { useState, useCallback, useRef, useMemo } from 'react';
import { useWebSocket, LogEntry } from './hooks/useWebSocket';
import { useAudioPlayer } from './hooks/useAudioPlayer';
import { JobInfo, setVfo, toggleAudio } from './api';
import ControlPanel, { ControlPanelHandle } from './components/ControlPanel';
import LogConsole from './components/LogConsole';
import JobList from './components/JobList';
import ResultView from './components/ResultView';
import SpectrumChart, { SpectrumFrame, ChartView, TYPE_COLORS, TYPE_LABELS } from './components/SpectrumChart';
import WaterfallCanvas from './components/WaterfallCanvas';

const WS_URL = `ws://${window.location.hostname}:8900/api/ws`;
const AUDIO_WS_URL = `ws://${window.location.hostname}:8900/api/ws/audio`;

// ── Signal table styles ──────────────────────────────────

const signalRow = 'flex items-center gap-3 px-3 py-1.5 rounded cursor-pointer hover:bg-gray-700/30 transition-colors text-xs font-mono';
const signalRowActive = 'bg-cyan-500/10 border-l-2 border-cyan-400';
const sortBtn = 'px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors';
const sortBtnActive = 'bg-cyan-500/20 text-cyan-300';
const sortBtnInactive = 'text-gray-600 hover:text-gray-400';
const sectionToggle = 'flex items-center justify-between w-full px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 transition-colors uppercase tracking-wider';
// ── Local components ─────────────────────────────────────

function SignalTable({ peaks, vfoFreq, onFreqClick }: {
  peaks: SpectrumFrame['peaks'];
  vfoFreq: number | null;
  onFreqClick: (freq_mhz: number) => void;
}) {
  const [sortBy, setSortBy] = useState<'freq' | 'power'>('freq');

  const sorted = useMemo(() => {
    const arr = [...peaks];
    if (sortBy === 'freq') arr.sort((a, b) => a.freq_mhz - b.freq_mhz);
    else arr.sort((a, b) => b.power_db - a.power_db);
    return arr;
  }, [peaks, sortBy]);

  const closestIdx = useMemo(() => {
    if (vfoFreq == null || sorted.length === 0) return -1;
    let best = 0;
    let bestDist = Math.abs(sorted[0].freq_mhz - vfoFreq);
    for (let i = 1; i < sorted.length; i++) {
      const d = Math.abs(sorted[i].freq_mhz - vfoFreq);
      if (d < bestDist) { best = i; bestDist = d; }
    }
    return bestDist < 0.1 ? best : -1;
  }, [sorted, vfoFreq]);

  if (peaks.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600 text-sm italic font-mono">
        No signals detected
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-3 py-1.5 border-b border-gray-700/30 flex-shrink-0">
        <span className="text-[10px] text-gray-500 uppercase tracking-wider">Sort</span>
        <div className="flex gap-1">
          <button onClick={() => setSortBy('freq')}
            className={`${sortBtn} ${sortBy === 'freq' ? sortBtnActive : sortBtnInactive}`}>
            Freq
          </button>
          <button onClick={() => setSortBy('power')}
            className={`${sortBtn} ${sortBy === 'power' ? sortBtnActive : sortBtnInactive}`}>
            Power
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {sorted.map((pk, i) => {
          const color = (pk.signal_type && TYPE_COLORS[pk.signal_type]) || '#888888';
          const label = pk.signal_type ? (TYPE_LABELS[pk.signal_type] || '?') : '?';
          return (
            <div
              key={pk.freq_mhz.toFixed(4)}
              onClick={() => onFreqClick(pk.freq_mhz)}
              className={`${signalRow} ${i === closestIdx ? signalRowActive : ''}`}
            >
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold w-8 text-center"
                style={{ backgroundColor: color + '25', color }}>
                {label}
              </span>
              <span className="text-gray-200 w-24">{pk.freq_mhz.toFixed(3)} MHz</span>
              <span className="text-gray-400 w-16">{pk.power_db.toFixed(1)} dB</span>
              <span className="text-gray-600 w-14">{pk.bandwidth_khz.toFixed(0)} kHz</span>
              {pk.duty_cycle != null && (
                <span className="text-gray-600 w-10">{(pk.duty_cycle * 100).toFixed(0)}%</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

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

function Sidebar({ controlPanelRef, liveActive, audioEnabled, onLiveToggle, onAudioToggle, onVolumeChange, vfoFreq, onVfoChange, peaks, onPeakClick, jobs, selectedJob, onSelectJob }: {
  controlPanelRef: React.Ref<ControlPanelHandle>;
  liveActive: boolean;
  audioEnabled: boolean;
  onLiveToggle: (active: boolean) => void;
  onAudioToggle: (enabled: boolean) => void;
  onVolumeChange: (v: number) => void;
  vfoFreq: number | null;
  onVfoChange: (freq_mhz: number) => void;
  peaks: SpectrumFrame['peaks'];
  onPeakClick: (freq_mhz: number) => void;
  jobs: JobInfo[];
  selectedJob: JobInfo | null;
  onSelectJob: (job: JobInfo | null) => void;
}) {
  const [signalsOpen, setSignalsOpen] = useState(true);

  return (
    <aside className="w-72 border-r border-gray-800 flex flex-col">
      <div className="p-3 border-b border-gray-800/50 flex-shrink-0">
        <ControlPanel
          ref={controlPanelRef}
          liveActive={liveActive}
          onLiveToggle={onLiveToggle}
          audioEnabled={audioEnabled}
          onAudioToggle={onAudioToggle}
          onVolumeChange={onVolumeChange}
          vfoFreq={vfoFreq}
          onVfoChange={onVfoChange}
        />
      </div>
      {peaks.length > 0 && (
        <div className="border-b border-gray-800/50 flex-shrink-0" style={{ maxHeight: signalsOpen ? '40%' : undefined }}>
          <button onClick={() => setSignalsOpen(o => !o)} className={sectionToggle}>
            <span>Signals ({peaks.length})</span>
            <span className="text-sm text-cyan-400">{signalsOpen ? '▲' : '▼'}</span>
          </button>
          {signalsOpen && (
            <SignalTable peaks={peaks} vfoFreq={vfoFreq} onFreqClick={onPeakClick} />
          )}
        </div>
      )}
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

function MainContent({ liveActive, liveFrame, selectedJob, logs, connected, onClear, vfoFreq, onFreqClick, onScanFreqClick }: {
  liveActive: boolean;
  liveFrame: SpectrumFrame | null;
  selectedJob: JobInfo | null;
  logs: LogEntry[];
  connected: boolean;
  onClear: () => void;
  vfoFreq: number | null;
  onFreqClick: (freq_mhz: number) => void;
  onScanFreqClick: (freq_mhz: number) => void;
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
          <ResultView job={selectedJob} onFreqClick={onScanFreqClick} />
        )}
      </div>
      <LogConsole logs={logs} connected={connected} onClear={onClear} />
    </div>
  );
}

// ── App ──────────────────────────────────────────────────

export default function App() {
  const audio = useAudioPlayer(AUDIO_WS_URL);
  const controlPanelRef = useRef<ControlPanelHandle>(null);
  const [selectedJob, setSelectedJob] = useState<JobInfo | null>(null);
  const [liveActive, setLiveActive] = useState(false);
  const [liveFrame, setLiveFrame] = useState<SpectrumFrame | null>(null);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [vfoFreq, setVfoFreq] = useState<number | null>(null);
  const audioRef = useRef(audio);
  audioRef.current = audio;

  const handleSpectrum = useCallback((data: any) => {
    const freqs: number[] = data.freqs_mhz;
    setLiveFrame({
      freqs_mhz: freqs,
      power_db: data.power_db,
      peaks: data.peaks,
    });
    const center = (freqs[0] + freqs[freqs.length - 1]) / 2;
    setVfoFreq(prev => {
      if (prev != null) {
        if (prev < freqs[0] || prev > freqs[freqs.length - 1]) {
          setAudioEnabled(false);
          audioRef.current.stop();
          setVfo(center).catch(() => {});
          return center;
        }
        return prev;
      }
      setVfo(center).catch(() => {});
      return center;
    });
  }, []);

  const { connected, logs, clearLogs, jobs } = useWebSocket(WS_URL, handleSpectrum);

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

  const handleScanPeakClick = useCallback((freq_mhz: number) => {
    controlPanelRef.current?.goLiveAt(freq_mhz);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-gray-100">
      <Header liveActive={liveActive} audioEnabled={audioEnabled} serverOnline={connected} />
      <div className="flex h-[calc(100vh-45px)]">
        <Sidebar
          controlPanelRef={controlPanelRef}
          liveActive={liveActive}
          audioEnabled={audioEnabled}
          onLiveToggle={handleLiveToggle}
          onAudioToggle={handleAudioToggle}
          onVolumeChange={audio.setVolume}
          vfoFreq={vfoFreq}
          onVfoChange={handleFreqClick}
          peaks={liveActive ? (liveFrame?.peaks || []) : (selectedJob?.status === 'complete' ? selectedJob.params.peaks ?? [] : [])}
          onPeakClick={liveActive ? handleFreqClick : handleScanPeakClick}
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
          onScanFreqClick={handleScanPeakClick}
        />
      </div>
    </div>
  );
}
