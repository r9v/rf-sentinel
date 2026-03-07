const API = '';

async function post(url: string, body?: object): Promise<Response> {
  const res = await fetch(`${API}${url}`, {
    method: 'POST',
    ...(body && {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res;
}

export interface JobResponse {
  job_id: string;
  status: string;
}

export interface JobInfo {
  id: string;
  type: string;
  status: 'pending' | 'running' | 'complete' | 'error' | 'cancelled';
  params: Record<string, any>;
  error: string | null;
  created_at: string;
  duration_s: number | null;
}

export async function startScan(params: {
  start_mhz: number; stop_mhz: number; duration: number; gain: number;
}): Promise<JobResponse> {
  return (await post('/api/scan', params)).json();
}

// ── Live mode ──────────────────────────────────────────

export async function startLive(params: {
  start_mhz: number; stop_mhz: number; gain: number;
  audio_enabled?: boolean; demod_mode?: string;
}): Promise<{ status: string; start_mhz: number; stop_mhz: number }> {
  return (await post('/api/live/start', params)).json();
}

export async function retuneLive(params: {
  start_mhz: number; stop_mhz: number; gain: number;
}): Promise<{ status: string }> {
  return (await post('/api/live/retune', params)).json();
}

export async function stopLive(): Promise<{ status: string }> {
  return (await post('/api/live/stop')).json();
}

export async function toggleAudio(params: {
  enabled: boolean; demod_mode: string;
}): Promise<{ audio_enabled: boolean; demod_mode: string }> {
  return (await post('/api/live/audio', params)).json();
}

export async function setVfo(freq_mhz: number): Promise<{ vfo_freq_mhz: number }> {
  return (await post('/api/live/vfo', { freq_mhz })).json();
}

// ── Scan history ──────────────────────────────────────

export interface ScanSummary {
  id: string;
  start_mhz: number;
  stop_mhz: number;
  duration: number;
  gain: number;
  created_at: string;
  duration_s: number | null;
  num_peaks: number;
}

export async function listScans(
  limit = 50, offset = 0,
): Promise<{ scans: ScanSummary[]; total: number }> {
  const res = await fetch(`${API}/api/scans?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function getScan(scanId: string): Promise<JobInfo> {
  const res = await fetch(`${API}/api/scans/${scanId}`);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function cancelJob(jobId: string): Promise<{ status: string }> {
  return (await post(`/api/jobs/${jobId}/cancel`)).json();
}

export async function deleteScan(scanId: string): Promise<{ status: string }> {
  const res = await fetch(`${API}/api/scans/${scanId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// ── Recordings ───────────────────────────────────────

export async function startRecording(
  mode: 'wide' | 'narrow', bandwidthKhz?: number,
): Promise<{ id: string; mode: string; filename: string }> {
  return (await post('/api/live/record/start', {
    mode, bandwidth_khz: bandwidthKhz,
  })).json();
}

export async function stopRecording(): Promise<Record<string, any>> {
  return (await post('/api/live/record/stop')).json();
}

export interface RecordingInfo {
  id: string;
  mode: string;
  filename: string;
  freq_mhz: number;
  bandwidth_khz: number | null;
  sample_rate: number;
  gain: number;
  start_mhz: number;
  stop_mhz: number;
  num_samples: number;
  file_size: number;
  created_at: string;
  stopped_at: string;
  duration_s: number;
}

export async function listRecordings(
  limit = 50, offset = 0,
): Promise<{ recordings: RecordingInfo[]; total: number }> {
  const res = await fetch(`${API}/api/recordings?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function deleteRecording(recId: string): Promise<{ status: string }> {
  const res = await fetch(`${API}/api/recordings/${recId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}


