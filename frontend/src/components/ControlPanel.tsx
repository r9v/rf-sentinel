import { useState, useCallback } from 'react';
import { startScan, startWaterfall, startLive, stopLive, toggleAudio } from '../api';
import ModeSelector, { Mode } from './ModeSelector';
import PresetBar from './PresetBar';
import ParamSlider from './ParamSlider';

export type DemodMode = 'fm' | 'am';

interface Props {
  onJobStarted: () => void;
  liveActive: boolean;
  onLiveToggle: (active: boolean) => void;
  audioEnabled: boolean;
  onAudioToggle: (enabled: boolean) => void;
  onVolumeChange: (v: number) => void;
}

const submitBtn = 'w-full py-2.5 rounded-lg font-medium text-sm transition-all';
const submitBtnDisabled = 'bg-gray-700 text-gray-400 cursor-not-allowed';
const submitBtnLiveActive = 'bg-red-600 hover:bg-red-500 text-white animate-pulse';
const submitBtnLive = 'bg-red-600 hover:bg-red-500 text-white';
const submitBtnScan = 'bg-cyan-600 hover:bg-cyan-500 text-white glow-accent';
const audioPanel = 'rounded-lg border border-gray-700/50 bg-gray-800/30 p-2.5 space-y-2';
const demodBtn = 'px-2.5 py-1 rounded text-xs font-mono transition-all';
const demodBtnActive = 'bg-cyan-600 text-white';
const demodBtnInactive = 'bg-gray-700/50 text-gray-400 hover:text-gray-200';

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

function AudioControls({ liveActive, audioEnabled, onToggle, volume, onVolumeChange }: {
  liveActive: boolean;
  audioEnabled: boolean;
  onToggle: (enabled: boolean) => void;
  volume: number;
  onVolumeChange: (v: number) => void;
}) {
  const [demodMode, setDemodMode] = useState<DemodMode>('fm');

  const handleToggle = async () => {
    const next = !audioEnabled;
    try {
      await toggleAudio({ enabled: next, demod_mode: demodMode });
      onToggle(next);
    } catch (e) {
      console.error('[ControlPanel] audio toggle failed:', e);
    }
  };

  const handleModeChange = async (mode: DemodMode) => {
    setDemodMode(mode);
    if (audioEnabled) {
      try {
        await toggleAudio({ enabled: true, demod_mode: mode });
        onToggle(true);
      } catch (e) {
        console.error('[ControlPanel] demod mode switch failed:', e);
      }
    }
  };

  if (!liveActive) return null;

  return (
    <div className={audioPanel}>
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400 uppercase tracking-wider">Audio</span>
        <button
          onClick={handleToggle}
          className={`px-2.5 py-1 rounded text-xs font-medium transition-all ${
            audioEnabled
              ? 'bg-green-600/80 text-white hover:bg-green-500'
              : 'bg-gray-700/50 text-gray-400 hover:text-gray-200'
          }`}
        >
          {audioEnabled ? '🔊 ON' : '🔇 OFF'}
        </button>
      </div>

      <div className="flex gap-1.5">
        {(['fm', 'am'] as DemodMode[]).map(m => (
          <button
            key={m}
            onClick={() => handleModeChange(m)}
            className={`${demodBtn} ${demodMode === m ? demodBtnActive : demodBtnInactive}`}
          >
            {m.toUpperCase()}
          </button>
        ))}
      </div>

      {audioEnabled && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 w-8">Vol</span>
          <input
            type="range"
            min={0}
            max={100}
            value={volume}
            onChange={e => onVolumeChange(Number(e.target.value))}
            className="flex-1 h-1 accent-cyan-500"
          />
          <span className="text-xs text-gray-500 w-7 text-right">{volume}%</span>
        </div>
      )}
    </div>
  );
}

export default function ControlPanel({ onJobStarted, liveActive, onLiveToggle, audioEnabled, onAudioToggle, onVolumeChange }: Props) {
  const [mode, setMode] = useState<Mode>('scan');
  const [startMhz, setStartMhz] = useState(97.0);
  const [stopMhz, setStopMhz] = useState(99.0);
  const [centerMhz, setCenterMhz] = useState(98.0);
  const [duration, setDuration] = useState(2.0);
  const [gain, setGain] = useState(30.0);
  const [loading, setLoading] = useState(false);
  const [volume, setVolume] = useState(50);

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

  const handleSubmit = async () => {
    if (!canRun) return;

    if (isLive) {
      if (liveActive) {
        await stopLive();
        onLiveToggle(false);
        onAudioToggle(false);
      } else {
        setLoading(true);
        try {
          await startLive({
            start_mhz: +(centerMhz - 1.0).toFixed(1),
            stop_mhz: +(centerMhz + 1.0).toFixed(1),
            gain,
          });
          onLiveToggle(true);
        } catch (e) {
          console.error('Failed to start live:', e);
        } finally {
          setLoading(false);
        }
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
      if (mode === 'scan') {
        await startScan(params);
      } else {
        await startWaterfall(params);
      }
      onJobStarted();
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

      <PresetBar
        activeStart={isLive ? centerMhz - 1 : startMhz}
        activeStop={isLive ? centerMhz + 1 : stopMhz}
        onSelect={handlePreset}
      />

      {/* Frequency controls */}
      {isLive ? (
        <div className="space-y-3">
          <ParamSlider label="Center Freq" value={centerMhz} onChange={setCenterMhz}
            min={24} max={1766} step={0.1} unit="MHz" logScale nudgeSteps={[0.1, 1, 10]} />
        </div>
      ) : (
        <>
          <div className="space-y-3">
            <ParamSlider label="Start Freq" value={startMhz} onChange={setStartMhz}
              min={24} max={1766} step={0.1} unit="MHz" logScale nudgeSteps={[0.1, 1, 10]} />
            <ParamSlider label="Stop Freq" value={stopMhz} onChange={setStopMhz}
              min={24} max={1766} step={0.1} unit="MHz" logScale nudgeSteps={[0.1, 1, 10]} />
          </div>

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
        volume={volume}
        onVolumeChange={handleVolumeChange}
      />
    </div>
  );
}
