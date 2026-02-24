import { useState } from 'react';
import { startScan, startWaterfall, startSweep } from '../api';

interface Props {
  onJobStarted: () => void;
}

type Mode = 'scan' | 'waterfall' | 'sweep';

export default function ControlPanel({ onJobStarted }: Props) {
  const [mode, setMode] = useState<Mode>('scan');
  const [freqMhz, setFreqMhz] = useState(98.0);
  const [rateMsps, setRateMsps] = useState(1.024);
  const [duration, setDuration] = useState(2.0);
  const [gain, setGain] = useState(30.0);
  const [loading, setLoading] = useState(false);

  const presets = [
    { label: 'FM Radio', freq: 98.0, rate: 2.048 },
    { label: 'Airband', freq: 127.0, rate: 2.048 },
    { label: 'PMR446', freq: 446.1, rate: 1.0 },
    { label: '433 IoT', freq: 433.9, rate: 2.048 },
    { label: '868 LoRa', freq: 868.0, rate: 2.048 },
    { label: 'GSM 900', freq: 947.0, rate: 2.048 },
    { label: 'ADS-B', freq: 1090.0, rate: 2.048 },
  ];

  const handleSubmit = async () => {
    setLoading(true);
    try {
      if (mode === 'scan') {
        await startScan({ freq_mhz: freqMhz, sample_rate_msps: rateMsps, duration, gain });
      } else if (mode === 'waterfall') {
        await startWaterfall({ freq_mhz: freqMhz, sample_rate_msps: rateMsps, duration, gain });
      } else {
        await startSweep({ gain });
      }
      onJobStarted();
    } catch (e) {
      console.error('Failed to start job:', e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Mode selector */}
      <div className="flex gap-1 p-1 bg-gray-800/50 rounded-lg">
        {(['scan', 'waterfall', 'sweep'] as Mode[]).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all capitalize
              ${mode === m
                ? 'bg-cyan-500/20 text-cyan-300 shadow-sm'
                : 'text-gray-400 hover:text-gray-200'
              }`}
          >
            {m}
          </button>
        ))}
      </div>

      {/* Presets */}
      {mode !== 'sweep' && (
        <div>
          <label className="text-xs text-gray-500 uppercase tracking-wider mb-1.5 block">
            Presets
          </label>
          <div className="flex flex-wrap gap-1.5">
            {presets.map(p => (
              <button
                key={p.label}
                onClick={() => { setFreqMhz(p.freq); setRateMsps(p.rate); }}
                className={`px-2 py-1 text-xs rounded border transition-all
                  ${freqMhz === p.freq
                    ? 'border-cyan-500/50 text-cyan-300 bg-cyan-500/10'
                    : 'border-gray-700 text-gray-400 hover:border-gray-600 hover:text-gray-300'
                  }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Parameters */}
      {mode !== 'sweep' && (
        <div className="space-y-3">
          <ParamSlider
            label="Frequency"
            value={freqMhz}
            onChange={setFreqMhz}
            min={24}
            max={1766}
            step={0.1}
            unit="MHz"
          />
          <ParamSlider
            label="Sample Rate"
            value={rateMsps}
            onChange={setRateMsps}
            min={0.25}
            max={2.56}
            step={0.064}
            unit="Msps"
          />
          <ParamSlider
            label="Duration"
            value={duration}
            onChange={setDuration}
            min={0.5}
            max={30}
            step={0.5}
            unit="s"
          />
        </div>
      )}

      <ParamSlider
        label="Gain"
        value={gain}
        onChange={setGain}
        min={0}
        max={50}
        step={1}
        unit="dB"
      />

      {/* Run button */}
      <button
        onClick={handleSubmit}
        disabled={loading}
        className={`w-full py-2.5 rounded-lg font-medium text-sm transition-all
          ${loading
            ? 'bg-gray-700 text-gray-400 cursor-wait'
            : 'bg-cyan-600 hover:bg-cyan-500 text-white glow-accent'
          }`}
      >
        {loading ? 'Starting...' : `Run ${mode.charAt(0).toUpperCase() + mode.slice(1)}`}
      </button>
    </div>
  );
}

function ParamSlider({ label, value, onChange, min, max, step, unit }: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  unit: string;
}) {
  return (
    <div>
      <div className="flex justify-between mb-1">
        <label className="text-xs text-gray-400">{label}</label>
        <span className="text-xs text-cyan-300 font-mono">
          {value % 1 === 0 ? value : value.toFixed(step < 1 ? 3 : 1)} {unit}
        </span>
      </div>
      <input
        type="range"
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        min={min}
        max={max}
        step={step}
        className="w-full h-1.5 bg-gray-700 rounded-lg appearance-none cursor-pointer
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3
          [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full
          [&::-webkit-slider-thumb]:bg-cyan-400 [&::-webkit-slider-thumb]:cursor-pointer"
      />
    </div>
  );
}
