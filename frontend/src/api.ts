const API = '';

export interface JobResponse {
  job_id: string;
  status: string;
}

export interface JobInfo {
  id: string;
  type: string;
  status: 'pending' | 'running' | 'complete' | 'error';
  params: Record<string, any>;
  result_url: string | null;
  error: string | null;
  created_at: string;
  duration_s: number | null;
}

export interface BandInfo {
  name: string;
  freq_mhz: number;
  rate_msps: number;
}

export async function getStatus(): Promise<{ status: string; demo_mode: boolean }> {
  const res = await fetch(`${API}/api/status`);
  return res.json();
}

export async function getBands(): Promise<Record<string, BandInfo>> {
  const res = await fetch(`${API}/api/bands`);
  return res.json();
}

export async function startScan(params: {
  freq_mhz: number;
  sample_rate_msps: number;
  duration: number;
  gain: number;
}): Promise<JobResponse> {
  const res = await fetch(`${API}/api/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function startWaterfall(params: {
  freq_mhz: number;
  sample_rate_msps: number;
  duration: number;
  gain: number;
}): Promise<JobResponse> {
  const res = await fetch(`${API}/api/waterfall`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function startSweep(params: {
  gain: number;
  bands?: string[];
}): Promise<JobResponse> {
  const res = await fetch(`${API}/api/sweep`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  return res.json();
}

export async function getJobs(): Promise<JobInfo[]> {
  const res = await fetch(`${API}/api/jobs`);
  return res.json();
}

export async function getJob(id: string): Promise<JobInfo> {
  const res = await fetch(`${API}/api/jobs/${id}`);
  return res.json();
}
