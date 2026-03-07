import { useState, useCallback, useEffect, useRef, forwardRef, useImperativeHandle, type Dispatch, type SetStateAction } from 'react';
import { startScan, startLive, retuneLive, stopLive, toggleAudio, toggleCapture, getCaptureStatus, saveBookmark, updateBookmark, deleteBookmark, type Bookmark } from '../api';
import ModeSelector, { Mode } from './ModeSelector';
import PresetBar from './PresetBar';
import ParamSlider from './ParamSlider';
import FreqInput from './FreqInput';
import AudioControls, { DemodMode } from './AudioControls';

export interface ControlPanelHandle {
  goLiveAt: (freq_mhz: number) => void;
}

interface Props {
  liveActive: boolean;
  onLiveToggle: (active: boolean) => void;
  audioEnabled: boolean;
  onAudioToggle: (enabled: boolean) => void;
  onVolumeChange: (v: number) => void;
  vfoFreq: number | null;
  onVfoChange: (freq_mhz: number) => void;
  recording: string | null;
  onRecord: (mode: 'wide' | 'narrow', bandwidthKhz?: number) => void;
  bookmarks: Bookmark[];
  setBookmarks: Dispatch<SetStateAction<Bookmark[]>>;
  narrowBw: number;
  onNarrowBwChange: (bw: number) => void;
}

const submitBtn = 'w-full py-2.5 rounded-lg font-medium text-sm transition-all';
const submitBtnDisabled = 'bg-gray-700 text-gray-400 cursor-not-allowed';
const submitBtnLiveActive = 'bg-red-600 hover:bg-red-500 text-white animate-pulse';
const submitBtnLive = 'bg-red-600 hover:bg-red-500 text-white';
const submitBtnScan = 'bg-cyan-600 hover:bg-cyan-500 text-white glow-accent';
const sectionToggle = 'flex items-center justify-between w-full text-xs text-gray-400 hover:text-gray-200 transition-colors';
const recBtn = 'flex-1 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center justify-center gap-1.5';
const recBtnIdle = 'bg-gray-700/50 text-gray-400 hover:bg-gray-600/50 hover:text-gray-200';
const recBtnActive = 'bg-red-500/20 text-red-300 animate-pulse';
const NARROW_BW_OPTIONS = [10, 25, 50, 100, 200] as const;

function ScanInfo({ bandwidth, numChunks, duration }: { bandwidth: number; numChunks: number; duration: number }) {
  const formatEst = () => {
    const total = numChunks * duration;
    if (total < 60) return `${total.toFixed(0)}s`;
    const m = Math.floor(total / 60);
    const s = Math.round(total % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };
  return (
    <div className="flex justify-between text-xs text-gray-500 px-0.5">
      <span>BW: <span className="text-gray-400">{bandwidth.toFixed(1)} MHz</span></span>
      {numChunks > 1 && <span>Chunks: <span className="text-gray-400">{numChunks}</span></span>}
      {numChunks > 1 && <span>Est: <span className="text-gray-400">~{formatEst()} total</span></span>}
    </div>
  );
}

export default forwardRef<ControlPanelHandle, Props>(function ControlPanel({ liveActive, onLiveToggle, audioEnabled, onAudioToggle, onVolumeChange, vfoFreq, onVfoChange, recording, onRecord, bookmarks, setBookmarks, narrowBw, onNarrowBwChange }, ref) {
  const [mode, setMode] = useState<Mode>('live');
  const [startMhz, setStartMhz] = useState(85.0);
  const [stopMhz, setStopMhz] = useState(140.0);
  const [centerMhz, setCenterMhz] = useState(104.2);
  const [duration, setDuration] = useState(2.0);
  const [gain, setGain] = useState(30.0);
  const [loading, setLoading] = useState(false);
  const [volume, setVolume] = useState(50);
  const [demodMode, setDemodMode] = useState<DemodMode>('fm');
  const [presetsOpen, setPresetsOpen] = useState(false);
  const [bookmarksOpen, setBookmarksOpen] = useState(true);
  const [bkFreq, setBkFreq] = useState('');
  const [bkLabel, setBkLabel] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [inputsOpen, setInputsOpen] = useState(true);
  const [capturing, setCapturing] = useState(false);
  const [captureLabel, setCaptureLabel] = useState('live');
  const lastLiveParams = useRef('');
  const retuning = useRef(false);

  useEffect(() => {
    if (!capturing) return;
    const id = setInterval(async () => {
      try {
        const res = await getCaptureStatus();
        if (!res.capturing) setCapturing(false);
      } catch { /* ignore */ }
    }, 2000);
    return () => clearInterval(id);
  }, [capturing]);

  useEffect(() => {
    if (!liveActive) {
      lastLiveParams.current = '';
      return;
    }
    const key = `${centerMhz}:${gain}`;
    if (!lastLiveParams.current) {
      lastLiveParams.current = key;
      return;
    }
    if (lastLiveParams.current === key) return;
    lastLiveParams.current = key;

    const timer = setTimeout(async () => {
      if (retuning.current) return;
      retuning.current = true;
      try {
        await retuneLive({
          start_mhz: +(centerMhz - 1.0).toFixed(1),
          stop_mhz: +(centerMhz + 1.0).toFixed(1),
          gain,
        });
      } catch (e) {
        console.error('Failed to retune:', e);
      } finally {
        retuning.current = false;
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [centerMhz, gain, liveActive]);

  const bandwidth = stopMhz - startMhz;
  const invalid = mode !== 'live' && stopMhz <= startMhz;
  const isLive = mode === 'live';
  const canRun = isLive || !invalid;

  const handlePreset = (start: number, stop: number) => {
    if (isLive) {
      setCenterMhz(+((start + stop) / 2).toFixed(3));
    } else {
      setStartMhz(start);
      setStopMhz(stop);
    }
  };

  const doStartLive = async (center: number) => {
    setLoading(true);
    try {
      await startLive({
        start_mhz: +(center - 1.0).toFixed(1),
        stop_mhz: +(center + 1.0).toFixed(1),
        gain,
        audio_enabled: true,
        demod_mode: demodMode,
      });
      onLiveToggle(true);
      await toggleAudio({ enabled: true, demod_mode: demodMode });
      onAudioToggle(true);
    } catch (e) {
      console.error('Failed to start live:', e);
    } finally {
      setLoading(false);
    }
  };

  useImperativeHandle(ref, () => ({
    goLiveAt(freq_mhz: number) {
      if (liveActive) return;
      setMode('live');
      setCenterMhz(freq_mhz);
      doStartLive(freq_mhz);
    },
  }));

  const handleSubmit = async () => {
    if (!canRun) return;

    if (isLive) {
      if (liveActive) {
        await stopLive();
        onLiveToggle(false);
        onAudioToggle(false);
      } else {
        await doStartLive(centerMhz);
      }
      return;
    }

    setLoading(true);
    try {
      const params = {
        start_mhz: +startMhz.toFixed(1),
        stop_mhz: +stopMhz.toFixed(1),
        duration,
        gain,
      };
      await startScan(params);
    } catch (e) {
      console.error('Failed to start job:', e);
    } finally {
      setLoading(false);
    }
  };

  const handleModeChange = useCallback(async (newMode: Mode) => {
    if (liveActive && newMode !== 'live') {
      await stopLive();
      onLiveToggle(false);
      onAudioToggle(false);
    }
    setMode(newMode);
  }, [liveActive, onLiveToggle, onAudioToggle]);

  const handleVolumeChange = useCallback((v: number) => {
    setVolume(v);
    onVolumeChange(v / 100);
  }, [onVolumeChange]);

  const numChunks = Math.max(1, Math.ceil(bandwidth / (2.048 * 0.8)));

  return (
    <div className="space-y-4">
      <ModeSelector mode={mode} onChange={handleModeChange} />

      <div>
        <button onClick={() => setPresetsOpen(o => !o)} className={sectionToggle}>
          <span className="uppercase tracking-wider">Presets</span>
          <span className="text-sm text-cyan-400">{presetsOpen ? '▲' : '▼'}</span>
        </button>
        {presetsOpen && (
          <div className="mt-2">
            <PresetBar
              activeStart={isLive ? centerMhz - 1 : startMhz}
              activeStop={isLive ? centerMhz + 1 : stopMhz}
              onSelect={handlePreset}
            />
          </div>
        )}
      </div>

      <div>
        <button onClick={() => setBookmarksOpen(o => !o)} className={sectionToggle}>
          <span className="uppercase tracking-wider">Bookmarks</span>
          <span className="text-sm text-cyan-400">{bookmarksOpen ? '▲' : '▼'}</span>
        </button>
        {bookmarksOpen && (
          <div className="mt-2 space-y-2">
            {bookmarks.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {bookmarks.map(bk => (
                  <span key={bk.id} className="group flex items-center gap-0.5">
                    <button
                      onClick={() => {
                        setEditingId(bk.id);
                        setBkFreq(String(bk.freq_mhz));
                        setBkLabel(bk.label);
                      }}
                      title={`${bk.freq_mhz} MHz — click to edit`}
                      className={`px-2 py-1 text-xs rounded-l border transition-all ${editingId === bk.id ? 'border-cyan-500 text-cyan-300 bg-cyan-500/10' : 'border-gray-700 text-gray-400 hover:border-cyan-500/50 hover:text-cyan-300'}`}
                    >
                      {bk.label}
                      <span className="ml-1 text-gray-600">{bk.freq_mhz}</span>
                    </button>
                    <button
                      onClick={async () => {
                        await deleteBookmark(bk.id);
                        setBookmarks(prev => prev.filter(b => b.id !== bk.id));
                        if (editingId === bk.id) { setEditingId(null); setBkFreq(''); setBkLabel(''); }
                      }}
                      className="px-1 py-1 text-xs rounded-r border border-l-0 border-gray-700 text-gray-600 hover:text-red-400 hover:border-red-500/50 transition-all"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="space-y-1.5">
              <input
                value={bkFreq}
                onChange={e => setBkFreq(e.target.value)}
                placeholder="Frequency (MHz)"
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 focus:border-cyan-500 focus:outline-none"
              />
              <input
                value={bkLabel}
                onChange={e => setBkLabel(e.target.value)}
                placeholder="Label"
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 focus:border-cyan-500 focus:outline-none"
              />
              <div className="flex gap-1.5">
                <button
                  onClick={async () => {
                    const freq = parseFloat(bkFreq);
                    if (!bkLabel.trim() || isNaN(freq)) return;
                    try {
                      if (editingId) {
                        await updateBookmark(editingId, bkLabel.trim(), freq);
                        setBookmarks(prev => prev.map(b => b.id === editingId ? { ...b, label: bkLabel.trim(), freq_mhz: freq } : b).sort((a, b) => a.freq_mhz - b.freq_mhz));
                        setEditingId(null);
                      } else {
                        const { id } = await saveBookmark(bkLabel.trim(), freq);
                        setBookmarks(prev => [...prev, { id, label: bkLabel.trim(), freq_mhz: freq, notes: '', created_at: new Date().toISOString() }].sort((a, b) => a.freq_mhz - b.freq_mhz));
                      }
                      setBkFreq('');
                      setBkLabel('');
                    } catch (e) {
                      console.error('Failed to save bookmark:', e);
                    }
                  }}
                  disabled={!bkLabel.trim() || isNaN(parseFloat(bkFreq))}
                  className="flex-1 py-1.5 text-xs rounded border border-gray-700 text-gray-400 hover:border-cyan-500/50 hover:text-cyan-300 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  {editingId ? 'Update' : 'Save'}
                </button>
                {editingId && (
                  <button
                    onClick={() => { setEditingId(null); setBkFreq(''); setBkLabel(''); }}
                    className="px-3 py-1.5 text-xs rounded border border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200 transition-all"
                  >
                    Cancel
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      <div>
        <button onClick={() => setInputsOpen(o => !o)} className={sectionToggle}>
          <span className="uppercase tracking-wider">Inputs</span>
          <span className="text-sm text-cyan-400">{inputsOpen ? '▲' : '▼'}</span>
        </button>
        {inputsOpen && (
          <div className="mt-2 space-y-3">
            {isLive ? (
              <>
                <FreqInput label="Center Freq" value={centerMhz} onChange={setCenterMhz} min={24} max={1766} />
                {liveActive && vfoFreq != null && (
                  <FreqInput
                    label="VFO Freq"
                    value={vfoFreq}
                    onChange={onVfoChange}
                    min={+(centerMhz - 1.0).toFixed(1)}
                    max={+(centerMhz + 1.0).toFixed(1)}
                  />
                )}
              </>
            ) : (
              <>
                <FreqInput label="Start Freq" value={startMhz} onChange={setStartMhz} min={24} max={1766} />
                <FreqInput label="Stop Freq" value={stopMhz} onChange={setStopMhz} min={24} max={1766} />

                <ScanInfo bandwidth={bandwidth} numChunks={numChunks} duration={duration} />

                {invalid && (
                  <div className="text-xs text-red-400 bg-red-400/5 rounded px-2 py-1.5">
                    Stop frequency must be greater than start frequency.
                  </div>
                )}

                <ParamSlider label={numChunks > 1 ? 'Duration / chunk' : 'Duration'} value={duration} onChange={setDuration}
                  min={0.5} max={30} step={0.5} unit="s" />
              </>
            )}

            <ParamSlider label="Gain" value={gain} onChange={setGain}
              min={0} max={50} step={1} unit="dB" />
          </div>
        )}
      </div>

      <button
        onClick={handleSubmit}
        disabled={loading || !canRun}
        className={`${submitBtn} ${
          loading || !canRun ? submitBtnDisabled
          : isLive ? (liveActive ? submitBtnLiveActive : submitBtnLive)
          : submitBtnScan
        }`}
      >
        {isLive
          ? liveActive ? '■ Stop Live' : '● Start Live'
          : loading ? 'Starting...' : `Run ${mode.charAt(0).toUpperCase() + mode.slice(1)}`
        }
      </button>

      <AudioControls
        liveActive={liveActive}
        audioEnabled={audioEnabled}
        onToggle={onAudioToggle}
        demodMode={demodMode}
        onDemodModeChange={setDemodMode}
        volume={volume}
        onVolumeChange={handleVolumeChange}
      />

      {liveActive && (
        <div className="space-y-2">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">Recording</span>
          <div className="flex gap-2">
            <button
              onClick={() => onRecord('wide')}
              className={`${recBtn} ${recording === 'wide' ? recBtnActive : recBtnIdle}`}
            >
              {recording === 'wide' ? <>● Stop</> : <>Rec Band</>}
            </button>
            {vfoFreq != null && (
              <button
                onClick={() => onRecord('narrow', narrowBw)}
                className={`${recBtn} ${recording === 'narrow' ? recBtnActive : recBtnIdle}`}
              >
                {recording === 'narrow' ? <>● Stop</> : <>Rec VFO</>}
              </button>
            )}
          </div>
          {vfoFreq != null && !recording && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-gray-500">BW</span>
              <select
                value={narrowBw}
                onChange={e => onNarrowBwChange(+e.target.value)}
                className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 focus:border-cyan-500 focus:outline-none"
              >
                {NARROW_BW_OPTIONS.map(bw => (
                  <option key={bw} value={bw}>{bw} kHz</option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}

      {liveActive && (
        <div className="space-y-2">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">ML Debug</span>
          {!capturing && (
            <input
              value={captureLabel}
              onChange={e => setCaptureLabel(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ''))}
              placeholder="label"
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 focus:border-cyan-500 focus:outline-none"
            />
          )}
          <button
            onClick={async () => {
              try {
                const res = await toggleCapture(!capturing, 3, captureLabel || 'live');
                setCapturing(res.capturing);
              } catch (e) {
                console.error('Capture toggle failed:', e);
              }
            }}
            className={`${recBtn} w-full ${capturing ? recBtnActive : recBtnIdle}`}
          >
            {capturing ? '● Capturing...' : 'Capture 3 Snippets'}
          </button>
        </div>
      )}
    </div>
  );
});
