import { useState, useCallback, useEffect, useRef } from 'react';
import { startScan, startWaterfall, startLive, retuneLive, stopLive, toggleAudio } from '../api';
import ModeSelector, { Mode } from './ModeSelector';
import PresetBar from './PresetBar';
import ParamSlider from './ParamSlider';

export type DemodMode = 'fm' | 'am';

const FREQ_STEPS = [1000, 100, 10, 1, 0.1];
const arrowBtn = 'w-full flex justify-center text-xs leading-none text-gray-500 hover:text-cyan-300 transition-colors select-none cursor-pointer';
const digitInput = 'w-[22px] text-center text-base font-mono text-cyan-300 bg-transparent outline-none caret-cyan-400 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none';

function FreqInput({ label, value, onChange, min, max }: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
}) {
  const clamp = (v: number) => Math.min(max, Math.max(min, +v.toFixed(1)));
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const str = Math.floor(value).toString().padStart(4, '0');
  const tenths = Math.round((value % 1) * 10);
  const digits = [+str[0], +str[1], +str[2], +str[3], tenths];

  const setDigit = (i: number, d: number) => {
    const cur = [...digits];
    cur[i] = d;
    const v = cur[0] * 1000 + cur[1] * 100 + cur[2] * 10 + cur[3] + cur[4] * 0.1;
    onChange(clamp(v));
    if (i < 4) inputRefs.current[i + 1]?.focus();
  };

  const handleKey = (i: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    const d = parseInt(e.key);
    if (!isNaN(d) && d >= 0 && d <= 9) {
      e.preventDefault();
      setDigit(i, d);
      return;
    }
    if (e.key === 'ArrowUp') { e.preventDefault(); onChange(clamp(value + FREQ_STEPS[i])); }
    if (e.key === 'ArrowDown') { e.preventDefault(); onChange(clamp(value - FREQ_STEPS[i])); }
    if (e.key === 'ArrowRight' && i < 4) { e.preventDefault(); inputRefs.current[i + 1]?.focus(); }
    if (e.key === 'ArrowLeft' && i > 0) { e.preventDefault(); inputRefs.current[i - 1]?.focus(); }
    if (e.key === '.' && i < 4) { e.preventDefault(); inputRefs.current[4]?.focus(); }
  };

  return (
    <div>
      <label className="text-xs text-gray-400 mb-1 block">{label}</label>
      <div className="flex items-center justify-end">
        {digits.map((d, i) => (
          <div key={i} className="flex items-center">
            {i === 4 && <span className="text-base font-mono text-gray-500 leading-tight mx-px">.</span>}
            <div className="flex flex-col items-center" style={{ width: 22 }}>
              <button className={arrowBtn} onClick={() => onChange(clamp(value + FREQ_STEPS[i]))}>▲</button>
              <input
                ref={el => { inputRefs.current[i] = el; }}
                type="text"
                inputMode="numeric"
                value={d}
                readOnly
                onKeyDown={e => handleKey(i, e)}
                onFocus={e => e.target.select()}
                className={digitInput}
              />
              <button className={arrowBtn} onClick={() => onChange(clamp(value - FREQ_STEPS[i]))}>▼</button>
            </div>
          </div>
        ))}
        <span className="text-xs text-gray-500 ml-1.5">MHz</span>
      </div>
    </div>
  );
}

interface Props {
  liveActive: boolean;
  onLiveToggle: (active: boolean) => void;
  audioEnabled: boolean;
  onAudioToggle: (enabled: boolean) => void;
  onVolumeChange: (v: number) => void;
  vfoFreq: number | null;
  onVfoChange: (freq_mhz: number) => void;
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

function AudioControls({ liveActive, audioEnabled, onToggle, demodMode, onDemodModeChange, volume, onVolumeChange }: {
  liveActive: boolean;
  audioEnabled: boolean;
  onToggle: (enabled: boolean) => void;
  demodMode: DemodMode;
  onDemodModeChange: (mode: DemodMode) => void;
  volume: number;
  onVolumeChange: (v: number) => void;
}) {
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
    onDemodModeChange(mode);
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

export default function ControlPanel({ liveActive, onLiveToggle, audioEnabled, onAudioToggle, onVolumeChange, vfoFreq, onVfoChange }: Props) {
  const [mode, setMode] = useState<Mode>('scan');
  const [startMhz, setStartMhz] = useState(97.0);
  const [stopMhz, setStopMhz] = useState(99.0);
  const [centerMhz, setCenterMhz] = useState(104.2);
  const [duration, setDuration] = useState(2.0);
  const [gain, setGain] = useState(30.0);
  const [loading, setLoading] = useState(false);
  const [volume, setVolume] = useState(50);
  const [demodMode, setDemodMode] = useState<DemodMode>('fm');
  const [presetsOpen, setPresetsOpen] = useState(false);
  const [inputsOpen, setInputsOpen] = useState(true);
  const lastLiveParams = useRef('');

  // Debounced retune: restart live stream when freq/gain change
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
      try {
        await retuneLive({
          start_mhz: +(centerMhz - 1.0).toFixed(1),
          stop_mhz: +(centerMhz + 1.0).toFixed(1),
          gain,
        });
      } catch (e) {
        console.error('Failed to retune:', e);
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
        <button
          onClick={() => setPresetsOpen(o => !o)}
          className="flex items-center justify-between w-full text-xs text-gray-400 hover:text-gray-200 transition-colors"
        >
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
        <button
          onClick={() => setInputsOpen(o => !o)}
          className="flex items-center justify-between w-full text-xs text-gray-400 hover:text-gray-200 transition-colors"
        >
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
    </div>
  );
}
