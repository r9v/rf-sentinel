import { JobInfo } from '../api';
import SpectrumChart from './SpectrumChart';

interface Props {
  job: JobInfo | null;
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
      {job.result_url && (
        <a
          href={job.result_url}
          target="_blank"
          rel="noopener"
          className="text-xs text-gray-500 hover:text-cyan-400 transition-colors"
        >
          Open full size ↗
        </a>
      )}
    </div>
  );
}

function ScanResult({ job }: { job: JobInfo }) {
  const sd = job.params.spectrum_data;
  if (!sd) return <p className="text-gray-500 text-sm">No spectrum data available</p>;

  const frame = {
    freqs_mhz: sd.freqs_mhz,
    power_db: sd.power_db,
    peaks: job.params.peaks ?? [],
  };

  return <SpectrumChart frame={frame} mode="scan" width={900} height={400} />;
}

function WaterfallResult({ job }: { job: JobInfo }) {
  if (!job.result_url) return <p className="text-gray-500 text-sm">No plot available</p>;
  return (
    <img
      src={job.result_url}
      alt="waterfall result"
      className="max-w-full max-h-full object-contain rounded"
    />
  );
}

export default function ResultView({ job }: Props) {
  if (!job) return <EmptyState />;
  if (job.status === 'pending' || job.status === 'running') return <LoadingState job={job} />;
  if (job.status === 'error') return <ErrorState job={job} />;

  return (
    <div className="flex flex-col h-full">
      <JobHeader job={job} />
      <div className="flex-1 overflow-auto p-2 flex items-center justify-center">
        {job.type === 'scan' ? <ScanResult job={job} /> : <WaterfallResult job={job} />}
      </div>
    </div>
  );
}
