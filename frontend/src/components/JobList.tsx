import { useState, useEffect, useCallback } from 'react';
import { getJobs, JobInfo } from '../api';

interface Props {
  refreshTrigger: number;
  onSelectJob: (job: JobInfo) => void;
  selectedJobId: string | null;
}

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-yellow-500/20 text-yellow-300',
  running: 'bg-blue-500/20 text-blue-300',
  complete: 'bg-green-500/20 text-green-300',
  error: 'bg-red-500/20 text-red-300',
};

const TYPE_ICON: Record<string, string> = {
  scan: '📊',
  waterfall: '🌊',
  sweep: '📡',
};

interface JobCardProps {
  job: JobInfo;
  selected: boolean;
  onSelect: (job: JobInfo) => void;
}

function JobCard({ job, selected, onSelect }: JobCardProps) {
  return (
    <button
      onClick={() => onSelect(job)}
      className={`w-full text-left px-3 py-2 rounded-lg border transition-all
        ${selected
          ? 'border-cyan-500/40 bg-cyan-500/5'
          : 'border-gray-700/50 hover:border-gray-600 bg-gray-800/30'
        }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm">{TYPE_ICON[job.type] || '📦'}</span>
          <span className="text-sm text-gray-200 capitalize">{job.type}</span>
          {job.type !== 'sweep' && job.params.freq_mhz && (
            <span className="text-xs text-gray-500 font-mono">
              {job.params.freq_mhz} MHz
            </span>
          )}
        </div>
        <span className={`text-xs px-1.5 py-0.5 rounded ${STATUS_STYLE[job.status]}`}>
          {job.status}
        </span>
      </div>
      <div className="flex items-center justify-between mt-1">
        <span className="text-xs text-gray-600 font-mono">{job.id.slice(0, 8)}</span>
        {job.duration_s !== null && (
          <span className="text-xs text-gray-600">{job.duration_s}s</span>
        )}
      </div>
    </button>
  );
}

export default function JobList({ refreshTrigger, onSelectJob, selectedJobId }: Props) {
  const [jobs, setJobs] = useState<JobInfo[]>([]);

  const fetchJobs = useCallback(async () => {
    try {
      const data = await getJobs();
      setJobs(data);
    } catch { /* server not ready */ }
  }, []);

  // Poll every 2s while any job is running
  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 2000);
    return () => clearInterval(interval);
  }, [fetchJobs, refreshTrigger]);

  if (jobs.length === 0) {
    return (
      <div className="text-center py-8 text-gray-600 text-sm italic">
        No jobs yet. Run a scan to get started.
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {jobs.map(job => (
        <JobCard
          key={job.id}
          job={job}
          selected={selectedJobId === job.id}
          onSelect={onSelectJob}
        />
      ))}
    </div>
  );
}
