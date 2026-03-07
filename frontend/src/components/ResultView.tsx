import { useCallback, useRef, useState } from 'react';
import { JobInfo } from '../api';
import SpectrumChart, { ChartView } from './SpectrumChart';
import DualRangeSlider from './DualRangeSlider';
import WaterfallCanvas from './WaterfallCanvas';

interface Props {
  job: JobInfo | null;
  onFreqClick?: (freq_mhz: number) => void;
  peakFilter?: (pk: { transient?: boolean }) => boolean;
}

function EmptyState() {
  return (
    <div className="flex items-center justify-center h-full text-gray-600">
      <div className="text-center">
        <div className="text-4xl mb-3 opacity-30">📡</div>
        <p className="text-sm">Select a job to view results</p>
      </div>
    </div>
  );
}

function LoadingState({ job }: { job: JobInfo }) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <div className="animate-pulse text-cyan-400 text-lg mb-2">⟳</div>
        <p className="text-sm text-gray-400">
          {job.status === 'pending' ? 'Queued...' : 'Processing...'}
        </p>
        <p className="text-xs text-gray-600 mt-1 capitalize">
          {job.type} — {job.params.start_mhz}–{job.params.stop_mhz} MHz
        </p>
      </div>
    </div>
  );
}

function ErrorState({ job }: { job: JobInfo }) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center max-w-md">
        <div className="text-red-400 text-lg mb-2">✗</div>
        <p className="text-sm text-red-300 mb-2">Job failed</p>
        <pre className="text-xs text-red-400/70 bg-red-900/10 rounded p-3 text-left whitespace-pre-wrap">
          {job.error}
        </pre>
      </div>
    </div>
  );
}

function JobHeader({ job }: { job: JobInfo }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700/50">
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-200 capitalize font-medium">{job.type}</span>
        <span className="text-xs text-cyan-400 font-mono">
          {job.params.start_mhz}–{job.params.stop_mhz} MHz
        </span>
        {job.duration_s && (
          <span className="text-xs text-gray-500">{job.duration_s}s</span>
        )}
      </div>
    </div>
  );
}

function ScanResult({ job, onFreqClick, peakFilter }: { job: JobInfo; onFreqClick?: (freq_mhz: number) => void; peakFilter?: (pk: { transient?: boolean }) => boolean }) {
  const [chartView, setChartView] = useState<ChartView | null>(null);
  const [dataDbRange, setDataDbRange] = useState<[number, number]>([-120, -20]);
  const [dbRange, setDbRange] = useState<[number, number] | null>(null);
  const dataDbRef = useRef(dataDbRange);

  const onDataDbRange = useCallback((min: number, max: number) => {
    const r: [number, number] = [Math.floor(min), Math.ceil(max)];
    if (r[0] !== dataDbRef.current[0] || r[1] !== dataDbRef.current[1]) {
      dataDbRef.current = r;
      setDataDbRange(r);
    }
  }, []);

  const wd = job.params.waterfall_data;
  if (!wd) return <p className="text-gray-500 text-sm">No waterfall data available</p>;

  const sd = job.params.spectrum_data;
  const frame = sd ? {
    freqs_mhz: sd.freqs_mhz,
    power_db: sd.power_db,
    peaks: (job.params.peaks ?? []).filter(peakFilter || (() => true)),
  } : null;

  const sliderLo = dbRange ? dbRange[0] : dataDbRange[0];
  const sliderHi = dbRange ? dbRange[1] : dataDbRange[1];

  return (
    <div className="flex flex-col h-full">
      {frame && (
        <div className="flex-[2] min-h-0">
          <SpectrumChart frame={frame} mode="scan" onFreqClick={onFreqClick} onViewChange={setChartView} />
        </div>
      )}
      <div className="flex-1 min-h-0 flex">
        <div className="flex-1 min-w-0">
          <WaterfallCanvas resultData={wd} view={chartView} dbRange={dbRange} onDataDbRange={onDataDbRange} />
        </div>
        <div className="flex-shrink-0 py-1" style={{ width: 24 }}>
          <DualRangeSlider
            lo={sliderLo} hi={sliderHi}
            min={dataDbRange[0]} max={dataDbRange[1]}
            onChange={(lo, hi) => setDbRange([lo, hi])}
            onReset={() => setDbRange(null)}
            vertical snapStep={1} precision={0}
          />
        </div>
      </div>
    </div>
  );
}

export default function ResultView({ job, onFreqClick, peakFilter }: Props) {
  if (!job) return <EmptyState />;
  if (job.status === 'pending' || job.status === 'running') return <LoadingState job={job} />;
  if (job.status === 'error') return <ErrorState job={job} />;

  return (
    <div className="flex flex-col h-full">
      <JobHeader job={job} />
      <div className="flex-1 min-h-0">
        <ScanResult job={job} onFreqClick={onFreqClick} peakFilter={peakFilter} />
      </div>
    </div>
  );
}
