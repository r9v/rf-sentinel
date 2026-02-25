import { useState } from 'react';
import { startScan, startWaterfall } from '../api';
import ModeSelector, { Mode } from './ModeSelector';
import PresetBar from './PresetBar';
import ParamSlider from './ParamSlider';

interface Props {
  onJobStarted: () => void;
}

const MAX_BW_MHZ = 2.4; // Per-chunk bandwidth (RTL-SDR limit)

export default function ControlPanel({ onJobStarted }: Props) {
  const [mode, setMode] = useState<Mode>('scan');
  const [startMhz, setStartMhz] = useState(97.0);
  const [stopMhz, setStopMhz] = useState(99.0);
  const [duration, setDuration] = useState(2.0);
  const [gain, setGain] = useState(30.0);
  const [loading, setLoading] = useState(false);

  const bandwidth = stopMhz - startMhz;
  const invalid = stopMhz <= startMhz;
  const canRun = !invalid;

  const handlePreset = (start: number, stop: number) => {
    setStartMhz(start);
    setStopMhz(stop);
  };

  const handleSubmit = async () => {
    if (!canRun) return;
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

  const numChunks = Math.max(1, Math.ceil(bandwidth / (2.048 * 0.8)));

  return (
    <div className="space-y-4">
      <ModeSelector mode={mode} onChange={setMode} />

      <PresetBar
        activeStart={startMhz}
        activeStop={stopMhz}
        onSelect={handlePreset}
      />

      <div className="space-y-3">
        <ParamSlider label="Start Freq" value={startMhz} onChange={setStartMhz}
          min={24} max={1766} step={0.1} unit="MHz" logScale nudgeSteps={[0.1, 1, 10]} />
        <ParamSlider label="Stop Freq" value={stopMhz} onChange={setStopMhz}
          min={24} max={1766} step={0.1} unit="MHz" logScale nudgeSteps={[0.1, 1, 10]} />
      </div>

      {/* Computed info */}
      <div className="flex justify-between text-xs text-gray-500 px-0.5">
        <span>BW: <span className="text-gray-400">{bandwidth.toFixed(1)} MHz</span></span>
        {numChunks > 1 && (
          <span>Chunks: <span className="text-gray-400">{numChunks}</span></span>
        )}
        {numChunks > 1 && (
          <span>Est: <span className="text-gray-400">~{(() => {
            const total = numChunks * duration;
            if (total < 60) return `${total.toFixed(0)}s`;
            const m = Math.floor(total / 60);
            const s = Math.round(total % 60);
            return `${m}:${s.toString().padStart(2, '0')}`;
          })()} total</span></span>
        )}
      </div>

      {invalid && (
        <div className="text-xs text-red-400 bg-red-400/5 rounded px-2 py-1.5">
          Stop frequency must be greater than start frequency.
        </div>
      )}

      <ParamSlider label={numChunks > 1 ? 'Duration / chunk' : 'Duration'} value={duration} onChange={setDuration}
        min={0.5} max={30} step={0.5} unit="s" />

      <ParamSlider label="Gain" value={gain} onChange={setGain}
        min={0} max={50} step={1} unit="dB" />

      <button
        onClick={handleSubmit}
        disabled={loading || !canRun}
        className={`w-full py-2.5 rounded-lg font-medium text-sm transition-all
          ${loading || !canRun
            ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
            : 'bg-cyan-600 hover:bg-cyan-500 text-white glow-accent'
          }`}
      >
        {loading ? 'Starting...' : `Run ${mode.charAt(0).toUpperCase() + mode.slice(1)}`}
      </button>
    </div>
  );
}
