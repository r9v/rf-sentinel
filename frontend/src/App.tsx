import { useState, useCallback, useRef, useMemo, useEffect } from 'react';
import { useWebSocket, LogEntry } from './hooks/useWebSocket';
import { useAudioPlayer } from './hooks/useAudioPlayer';
import { JobInfo, setVfo, toggleAudio, getScan, cancelJob, deleteScan, startRecording, stopRecording } from './api';
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
const filterCheck = 'flex items-center gap-1 cursor-pointer text-[10px]';
// ── Local components ─────────────────────────────────────

function SignalTable({ peaks, vfoFreq, onFreqClick, showSteady, showTransient, onShowSteadyChange, onShowTransientChange }: {
  peaks: SpectrumFrame['peaks'];
  vfoFreq: number | null;
  onFreqClick: (freq_mhz: number) => void;
  showSteady: boolean;
  showTransient: boolean;
  onShowSteadyChange: (v: boolean) => void;
  onShowTransientChange: (v: boolean) => void;
}) {
  const [sortBy, setSortBy] = useState<'freq' | 'power'>('power');

  const sorted = useMemo(() => {
    const arr = peaks.filter(pk => pk.transient ? showTransient : showSteady);
    if (sortBy === 'freq') arr.sort((a, b) => a.freq_mhz - b.freq_mhz);
    else arr.sort((a, b) => b.power_db - a.power_db);
    return arr;
  }, [peaks, sortBy, showSteady, showTransient]);

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
        <span className="text-gray-700">|</span>
        <label className={filterCheck}>
          <input type="checkbox" checked={showSteady} onChange={e => onShowSteadyChange(e.target.checked)}
            className="accent-cyan-500 w-3 h-3" />
          <span className={showSteady ? 'text-gray-400' : 'text-gray-600'}>Steady</span>
        </label>
        <label className={filterCheck}>
          <input type="checkbox" checked={showTransient} onChange={e => onShowTransientChange(e.target.checked)}
            className="accent-amber-500 w-3 h-3" />
          <span className={showTransient ? 'text-amber-400' : 'text-gray-600'}>Trans</span>
        </label>
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
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-center"
                style={{ backgroundColor: color + '25', color }}>
                {label}{pk.confidence != null ? ` ${(pk.confidence * 100).toFixed(0)}%` : ''}
              </span>
              <span className="text-gray-200 w-16">{pk.freq_mhz.toFixed(1)} M</span>
              <span className="text-gray-400 w-14">{pk.power_db.toFixed(1)} dB</span>
              <span className="text-gray-600 w-12">{pk.bandwidth_khz.toFixed(0)} kHz</span>
              {pk.duty_cycle != null && (
                <span className="text-gray-600 w-10">{(pk.duty_cycle * 100).toFixed(0)}%</span>
              )}
              {pk.transient && (
                <span className="px-1 py-0.5 rounded text-[9px] font-bold bg-amber-500/20 text-amber-400">T</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Header({ liveActive, audioEnabled, recording, serverOnline }: {
  liveActive: boolean; audioEnabled: boolean; recording: string | null; serverOnline: boolean;
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
        {recording && (
          <span className="text-xs px-2 py-0.5 rounded bg-red-500/20 text-red-400 font-mono animate-pulse">
            ● REC {recording.toUpperCase()}
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

function Sidebar({ controlPanelRef, liveActive, audioEnabled, onLiveToggle, onAudioToggle, onVolumeChange, vfoFreq, onVfoChange, jobs, selectedJob, onSelectJob, onCancelJob, onDeleteScan, recording, onRecord, narrowBw, onNarrowBwChange }: {
  controlPanelRef: React.Ref<ControlPanelHandle>;
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
  onCancelJob: (jobId: string) => void;
  onDeleteScan: (scanId: string) => void;
  recording: string | null;
  onRecord: (mode: 'wide' | 'narrow', bandwidthKhz?: number) => void;
  narrowBw: number;
  onNarrowBwChange: (bw: number) => void;
}) {
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
          recording={recording}
          onRecord={onRecord}
          narrowBw={narrowBw}
          onNarrowBwChange={onNarrowBwChange}
        />
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <h3 className="text-xs text-gray-500 uppercase tracking-wider mb-2">Jobs</h3>
        <JobList
          jobs={jobs}
          onSelectJob={onSelectJob}
          selectedJobId={selectedJob?.id || null}
          onCancel={onCancelJob}
          onDelete={onDeleteScan}
        />
      </div>
    </aside>
  );
}

function SignalPanel({ peaks, vfoFreq, onPeakClick, showSteady, showTransient, onShowSteadyChange, onShowTransientChange }: {
  peaks: SpectrumFrame['peaks'];
  vfoFreq: number | null;
  onPeakClick: (freq_mhz: number) => void;
  showSteady: boolean;
  showTransient: boolean;
  onShowSteadyChange: (v: boolean) => void;
  onShowTransientChange: (v: boolean) => void;
}) {
  return (
    <aside className="w-72 border-l border-gray-800 flex flex-col">
      <div className="px-3 py-2 border-b border-gray-800/50 flex-shrink-0">
        <span className="text-xs text-gray-400 uppercase tracking-wider">Signals ({peaks.length})</span>
      </div>
      <SignalTable peaks={peaks} vfoFreq={vfoFreq} onFreqClick={onPeakClick}
        showSteady={showSteady} showTransient={showTransient}
        onShowSteadyChange={onShowSteadyChange} onShowTransientChange={onShowTransientChange} />
    </aside>
  );
}

function MainContent({ liveActive, liveFrame, selectedJob, logs, connected, onClear, vfoFreq, onFreqClick, onScanFreqClick, peakFilter, narrowBw }: {
  liveActive: boolean;
  liveFrame: SpectrumFrame | null;
  selectedJob: JobInfo | null;
  logs: LogEntry[];
  connected: boolean;
  onClear: () => void;
  vfoFreq: number | null;
  onFreqClick: (freq_mhz: number) => void;
  onScanFreqClick: (freq_mhz: number) => void;
  peakFilter: (pk: { transient?: boolean }) => boolean;
  narrowBw: number;
}) {
  const [chartView, setChartView] = useState<ChartView | null>(null);

  return (
    <div className="flex-1 min-w-0 flex flex-col">
      <div className="flex-1 border-b border-gray-800 overflow-hidden flex flex-col">
        {liveActive || liveFrame ? (
          <>
            <div className="flex-[2] min-h-0">
              <SpectrumChart frame={liveFrame} mode="live" vfoFreq={vfoFreq} onFreqClick={onFreqClick} onViewChange={setChartView} narrowBw={narrowBw} />
            </div>
            <div className="flex-1 min-h-0 border-t border-gray-800/50">
              <WaterfallCanvas frame={liveFrame} view={chartView} />
            </div>
          </>
        ) : (
          <ResultView job={selectedJob} onFreqClick={onScanFreqClick} peakFilter={peakFilter} />
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
  const [showSteady, setShowSteady] = useState(true);
  const [showTransient, setShowTransient] = useState(true);
  const [vfoFreq, setVfoFreq] = useState<number | null>(null);
  const [recording, setRecording] = useState<string | null>(null);
  const [narrowBw, setNarrowBw] = useState(25);
  const audioRef = useRef(audio);
  audioRef.current = audio;
  const vfoRef = useRef<number | null>(null);
  vfoRef.current = vfoFreq;

  const handleSpectrum = useCallback((data: any) => {
    const freqs: number[] = data.freqs_mhz;
    setLiveFrame({
      freqs_mhz: freqs,
      power_db: data.power_db,
      peaks: data.peaks,
    });
    setRecording(data.recording ?? null);
    const center = (freqs[0] + freqs[freqs.length - 1]) / 2;
    const prev = vfoRef.current;
    if (prev != null) {
      if (prev < freqs[0] || prev > freqs[freqs.length - 1]) {
        setAudioEnabled(false);
        audioRef.current.stop();
        setVfoFreq(center);
        setVfo(center).catch(() => setVfoFreq(null));
      }
    } else {
      setVfoFreq(center);
      setVfo(center).catch(() => setVfoFreq(null));
    }
  }, []);

  const { connected, logs, clearLogs, jobs, setJobs } = useWebSocket(WS_URL, handleSpectrum);

  const peakFilter = useCallback((pk: { transient?: boolean }) => pk.transient ? showTransient : showSteady, [showSteady, showTransient]);

  const filteredLiveFrame = useMemo(() => {
    if (!liveFrame) return null;
    return { ...liveFrame, peaks: liveFrame.peaks.filter(peakFilter) };
  }, [liveFrame, peakFilter]);

  const handleSelectJob = useCallback(async (job: JobInfo | null) => {
    if (!job) { setSelectedJob(null); return; }
    if (job.params.spectrum_data) { setSelectedJob(job); return; }
    if (job.status === 'complete') {
      try {
        const full = await getScan(job.id);
        setJobs(prev => prev.map(j => j.id === job.id ? full : j));
        setSelectedJob(full);
      } catch { setSelectedJob(job); }
      return;
    }
    setSelectedJob(job);
  }, [setJobs]);

  const handleFreqClick = useCallback((freq_mhz: number) => {
    if (!liveActive) return;
    setVfoFreq(freq_mhz);
    setVfo(freq_mhz).catch(() => setVfoFreq(null));
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
      setRecording(null);
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

  const handleCancelJob = useCallback((jobId: string) => {
    cancelJob(jobId).catch(() => {});
  }, []);

  const handleDeleteScan = useCallback((scanId: string) => {
    deleteScan(scanId).then(() => {
      setJobs(prev => prev.filter(j => j.id !== scanId));
      setSelectedJob(prev => prev?.id === scanId ? null : prev);
    }).catch(() => {});
  }, [setJobs]);

  const handleRecord = useCallback((mode: 'wide' | 'narrow', bandwidthKhz?: number) => {
    if (recording) {
      stopRecording().catch(() => {});
    } else {
      startRecording(mode, bandwidthKhz).catch(() => {});
    }
  }, [recording]);

  const handleScanPeakClick = useCallback((freq_mhz: number) => {
    controlPanelRef.current?.goLiveAt(freq_mhz);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-gray-100">
      <Header liveActive={liveActive} audioEnabled={audioEnabled} recording={recording} serverOnline={connected} />
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
          jobs={jobs}
          selectedJob={selectedJob}
          onSelectJob={handleSelectJob}
          onCancelJob={handleCancelJob}
          onDeleteScan={handleDeleteScan}
          recording={recording}
          onRecord={handleRecord}
          narrowBw={narrowBw}
          onNarrowBwChange={setNarrowBw}
        />
        <MainContent
          liveActive={liveActive}
          liveFrame={filteredLiveFrame}
          selectedJob={selectedJob}
          logs={logs}
          connected={connected}
          onClear={clearLogs}
          vfoFreq={audioEnabled ? vfoFreq : null}
          onFreqClick={handleFreqClick}
          onScanFreqClick={handleScanPeakClick}
          peakFilter={peakFilter}
          narrowBw={narrowBw}
        />
        <SignalPanel
          peaks={liveActive ? (liveFrame?.peaks || []) : (selectedJob?.status === 'complete' ? selectedJob.params.peaks ?? [] : [])}
          vfoFreq={vfoFreq}
          onPeakClick={liveActive ? handleFreqClick : handleScanPeakClick}
          showSteady={showSteady}
          showTransient={showTransient}
          onShowSteadyChange={setShowSteady}
          onShowTransientChange={setShowTransient}
        />
      </div>
    </div>
  );
}
