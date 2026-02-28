import { useState, useRef, useEffect } from 'react';

interface Props {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  unit: string;
  logScale?: boolean;
  showSlider?: boolean;
  nudgeSteps?: number[];
}

function linToLog(value: number, min: number, max: number): number {
  const logMin = Math.log10(min);
  const logMax = Math.log10(max);
  const logVal = Math.log10(value);
  return (logVal - logMin) / (logMax - logMin);
}

function logToLin(position: number, min: number, max: number): number {
  const logMin = Math.log10(min);
  const logMax = Math.log10(max);
  return Math.pow(10, logMin + position * (logMax - logMin));
}

const numInput = 'w-20 text-xs text-right text-cyan-300 font-mono bg-gray-800 border border-cyan-500/40 rounded px-1.5 py-0.5 outline-none focus:border-cyan-400 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none';
const rangeInput = 'w-full h-1.5 bg-gray-700 rounded-lg appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-cyan-400 [&::-webkit-slider-thumb]:cursor-pointer';

export default function ParamSlider({
  label, value, onChange, min, max, step, unit,
  logScale = false, showSlider = true, nudgeSteps,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const steps = nudgeSteps ?? [step];

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const formatValue = (v: number) => {
    if (step >= 1) return v.toString();
    if (step >= 0.1) return v.toFixed(1);
    return v.toFixed(3);
  };

  const clamp = (v: number) => Math.min(max, Math.max(min, v));

  const nudge = (amount: number) => {
    onChange(clamp(+(value + amount).toFixed(6)));
  };

  const handleStartEdit = () => {
    setDraft(formatValue(value));
    setEditing(true);
  };

  const handleCommit = () => {
    const parsed = parseFloat(draft);
    if (!isNaN(parsed)) onChange(clamp(parsed));
    setEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleCommit();
    if (e.key === 'Escape') setEditing(false);
  };

  const sliderMin = logScale ? 0 : min;
  const sliderMax = logScale ? 1000 : max;
  const sliderStep = logScale ? 1 : step;
  const sliderValue = logScale ? linToLog(value, min, max) * 1000 : value;

  const handleSlider = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = parseFloat(e.target.value);
    if (logScale) {
      const v = logToLin(raw / 1000, min, max);
      const snapped = Math.round(v / step) * step;
      onChange(clamp(+snapped.toFixed(6)));
    } else {
      onChange(raw);
    }
  };

  const NudgeBtn = ({ amount, weight }: { amount: number; weight: number }) => {
    const isNeg = amount < 0;
    const abs = Math.abs(amount);
    const label = abs >= 1 ? abs.toString() : abs.toFixed(1);
    const arrows = isNeg ? '‹'.repeat(weight) : '›'.repeat(weight);
    return (
      <button
        onClick={() => nudge(amount)}
        className="h-5 px-0.5 flex items-center justify-center text-[10px] text-gray-400
          hover:text-cyan-300 hover:bg-cyan-500/10 rounded transition-colors"
        title={`${isNeg ? '−' : '+'}${label} ${unit}`}
      >
        <span className="tracking-[-2px]">{arrows}</span>
      </button>
    );
  };

  return (
    <div>
      <div className="flex justify-between mb-1 items-center">
        <label className="text-xs text-gray-400">{label}</label>
        <div className="flex items-center gap-0">
          {/* Decrease buttons: largest step first */}
          {[...steps].reverse().map((s, i) => (
            <NudgeBtn key={`dec-${s}`} amount={-s} weight={steps.length - i} />
          ))}

          {editing ? (
            <div className="flex items-center gap-1">
              <input
                ref={inputRef}
                type="number"
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onBlur={handleCommit}
                onKeyDown={handleKeyDown}
                min={min}
                max={max}
                step={step}
                className={numInput}
              />
              <span className="text-xs text-gray-500">{unit}</span>
            </div>
          ) : (
            <button
              onClick={handleStartEdit}
              className="text-xs text-cyan-300 font-mono hover:text-cyan-200
                hover:bg-cyan-500/10 rounded px-1.5 py-0.5 transition-colors"
              title="Click to type exact value"
            >
              {formatValue(value)} {unit}
            </button>
          )}

          {/* Increase buttons: smallest step first */}
          {steps.map((s, i) => (
            <NudgeBtn key={`inc-${s}`} amount={s} weight={i + 1} />
          ))}
        </div>
      </div>
      {showSlider && (
        <input
          type="range"
          value={sliderValue}
          onChange={handleSlider}
          min={sliderMin}
          max={sliderMax}
          step={sliderStep}
          className={rangeInput}
        />
      )}
    </div>
  );
}
