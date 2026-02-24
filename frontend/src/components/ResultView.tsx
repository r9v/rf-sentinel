import { JobInfo } from '../api';

interface Props {
  job: JobInfo | null;
}

export default function ResultView({ job }: Props) {
  if (!job) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600">
        <div className="text-center">
          <div className="text-4xl mb-3 opacity-30">📡</div>
          <p className="text-sm">Select a job to view results</p>
        </div>
      </div>
    );
  }

  if (job.status === 'pending' || job.status === 'running') {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="animate-pulse text-cyan-400 text-lg mb-2">⟳</div>
          <p className="text-sm text-gray-400">
            {job.status === 'pending' ? 'Queued...' : 'Processing...'}
          </p>
          <p className="text-xs text-gray-600 mt-1 capitalize">{job.type} — {job.params.freq_mhz || 'multi-band'} MHz</p>
        </div>
      </div>
    );
  }

  if (job.status === 'error') {
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

  // Complete — show the plot
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-700/50">
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-200 capitalize font-medium">{job.type}</span>
          {job.params.freq_mhz && (
            <span className="text-xs text-cyan-400 font-mono">{job.params.freq_mhz} MHz</span>
          )}
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
      <div className="flex-1 overflow-auto p-2 flex items-center justify-center">
        {job.result_url ? (
          <img
            src={job.result_url}
            alt={`${job.type} result`}
            className="max-w-full max-h-full object-contain rounded"
          />
        ) : (
          <p className="text-gray-500 text-sm">No plot available</p>
        )}
      </div>
    </div>
  );
}
