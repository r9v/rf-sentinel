import { useState, useCallback } from 'react';
import { startScan, startWaterfall, startLive, stopLive } from '../api';
import ModeSelector, { Mode } from './ModeSelector';
import PresetBar from './PresetBar';
import ParamSlider from './ParamSlider';

interface Props {
  onJobStarted: () => void;
  liveActive: boolean;
  onLiveToggle: (active: boolean) => void;
}

const MAX_LIVE_BW_MHZ = 2.0; // RTL-SDR single-chunk limit for live

export default function ControlPanel({ onJobStarted, liveActive, onLiveToggle }: Props) {
  const [mode, setMode] = useState<Mode>('scan');
  const [startMhz, setStartMhz] = useState(97.0);
  const [stopMhz, setStopMhz] = useState(99.0);
  const [duration, setDuration] = useState(2.0);
  const [gain, setGain] = useState(30.0);
  const [loading, setLoading] = useState(false);

  const bandwidth = stopMhz - startMhz;
  const invalid = stopMhz <= startMhz;
  const isLive = mode === 'live';
  const liveBwExceeded = isLive && bandwidth > MAX_LIVE_BW_MHZ;
  const canRun = !invalid;

  const handlePreset = (start: number, stop: number) => {
    if (isLive && (stop - start) > MAX_LIVE_BW_MHZ) {
      // Clamp to max live BW centered on preset
      const center = (start + stop) / 2;
      setStartMhz(+(center - MAX_LIVE_BW_MHZ / 2).toFixed(1));
      setStopMhz(+(center + MAX_LIVE_BW_MHZ / 2).toFixed(1));
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
      } else {
        setLoading(true);
        try {
          await startLive({
            start_mhz: +startMhz.toFixed(1),
            stop_mhz: +stopMhz.toFixed(1),
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
    // Stop live if switching away
    if (liveActive && newMode !== 'live') {
      await stopLive();
      onLiveToggle(false);
    }
    setMode(newMode);
  }, [liveActive, onLiveToggle]);

  const numChunks = Math.max(1, Math.ceil(bandwidth / (2.048 * 0.8)));

  return (
    <div className="space-y-4">
      <ModeSelector mode={mode} onChange={handleModeChange} />

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
        {!isLive && numChunks > 1 && (
          <span>Chunks: <span className="text-gray-400">{numChunks}</span></span>
        )}
        {!isLive && numChunks > 1 && (
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

      {liveBwExceeded && (
        <div className="text-xs text-yellow-400 bg-yellow-400/5 rounded px-2 py-1.5">
          Live mode limited to {MAX_LIVE_BW_MHZ} MHz. Range will be clamped.
        </div>
      )}

      {!isLive && (
        <ParamSlider label={numChunks > 1 ? 'Duration / chunk' : 'Duration'} value={duration} onChange={setDuration}
          min={0.5} max={30} step={0.5} unit="s" />
      )}

      <ParamSlider label="Gain" value={gain} onChange={setGain}
        min={0} max={50} step={1} unit="dB" />

      <button
        onClick={handleSubmit}
        disabled={loading || !canRun}
        className={`w-full py-2.5 rounded-lg font-medium text-sm transition-all
          ${loading || !canRun
            ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
            : isLive
              ? liveActive
                ? 'bg-red-600 hover:bg-red-500 text-white animate-pulse'
                : 'bg-red-600 hover:bg-red-500 text-white'
              : 'bg-cyan-600 hover:bg-cyan-500 text-white glow-accent'
          }`}
      >
        {isLive
          ? liveActive ? '■ Stop Live' : '● Start Live'
          : loading ? 'Starting...' : `Run ${mode.charAt(0).toUpperCase() + mode.slice(1)}`
        }
      </button>
    </div>
  );
}
