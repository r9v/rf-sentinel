import { useRef, useState, useCallback, useEffect } from 'react';

// ── Tunable constants ────────────────────────────────────────────────
// RATE_P: lower = smoother pitch, higher = faster correction
// TARGET_SAMPLES: higher = more latency but more jitter cushion
// MAX/MIN_RATE: widen if drift exceeds current bounds
const SAMPLE_RATE = 48000;
const RING_BUFFER_SECS = 2;                 // max ring buffer length (seconds)
const PREFILL_SAMPLES = 24000;              // 500ms — buffer before playback starts
const TARGET_SAMPLES = 24000;               // 500ms — buffer level we steer toward
const MAX_RATE = 1.05;                      // max playback rate (5% faster)
const MIN_RATE = 0.95;                      // min playback rate (5% slower)
const RATE_P = 0.1 / TARGET_SAMPLES;        // proportional gain — lower = smoother
const RATE_SMOOTH = 0.002;                  // EMA alpha for rate — lower = more stable pitch
const STATUS_INTERVAL = 750;                // worklet status every N render calls (~2s)

// ── AudioWorklet processor code ──────────────────────────────────────
// Accepts audio data via MessagePort (from Worker) or via main port fallback.
// Int16→Float32 conversion happens here on the audio thread.
const WORKLET_CODE = `
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ring = new Float32Array(${SAMPLE_RATE * RING_BUFFER_SECS});
    this._writePos = 0;
    this._readPos = 0;
    this._readFrac = 0;
    this._count = 0;
    this._underruns = 0;
    this._started = false;
    this._smoothRate = 1.0;

    this._handleAudio = (buf) => {
      const int16 = buf instanceof ArrayBuffer ? new Int16Array(buf) : null;
      const ring = this._ring;
      const len = ring.length;
      const n = int16 ? int16.length : 0;
      for (let i = 0; i < n; i++) {
        ring[this._writePos] = int16[i] / 32768;
        this._writePos = (this._writePos + 1) % len;
      }
      this._count = Math.min(this._count + n, len);
    };

    this.port.onmessage = (e) => {
      if (e.data && e.data.type === 'audio-port') {
        // Dedicated audio port from Worker via MessageChannel
        const audioPort = e.data.port;
        audioPort.onmessage = (ev) => this._handleAudio(ev.data);
      } else {
        this._handleAudio(e.data);
      }
    };
  }

  process(inputs, outputs) {
    const out = outputs[0][0];
    if (!out) return true;

    if (!this._started) {
      out.fill(0);
      if (this._count >= ${PREFILL_SAMPLES}) this._started = true;
      return true;
    }

    const needed = out.length;
    const ring = this._ring;
    const len = ring.length;

    const error = this._count - ${TARGET_SAMPLES};
    const instant = 1.0 + error * ${RATE_P};
    this._smoothRate += ${RATE_SMOOTH} * (instant - this._smoothRate);
    const rate = Math.min(${MAX_RATE}, Math.max(${MIN_RATE}, this._smoothRate));

    const inputNeeded = Math.ceil(needed * rate) + 1;

    if (this._count >= inputNeeded) {
      let frac = this._readFrac;
      let pos = this._readPos;
      for (let i = 0; i < needed; i++) {
        const idx0 = pos % len;
        const idx1 = (pos + 1) % len;
        out[i] = ring[idx0] + frac * (ring[idx1] - ring[idx0]);
        frac += rate;
        const whole = frac | 0;
        pos += whole;
        frac -= whole;
      }
      const consumed = pos - this._readPos;
      this._readPos = pos % len;
      this._readFrac = frac;
      this._count -= consumed;
    } else {
      out.fill(0);
      this._underruns++;
      if (this._underruns % 100 === 1) {
        this.port.postMessage({ type: 'underrun', count: this._underruns, buffered: this._count });
      }
    }

    if (currentFrame % ${STATUS_INTERVAL} === 0) {
      this.port.postMessage({ type: 'status', buffered: this._count, underruns: this._underruns, rate: rate.toFixed(4) });
    }

    return true;
  }
}
registerProcessor('pcm-processor', PCMProcessor);
`;

// ── Web Worker code ──────────────────────────────────────────────────
// Runs off main thread. Owns a dedicated WebSocket for audio binary
// frames and forwards them to the AudioWorklet via MessagePort.
const WORKER_CODE = `
let ws = null;
let audioPort = null;
let wsUrl = null;
let reconnectTimer = null;

function connect() {
  if (!wsUrl) return;
  if (ws) { ws.onclose = null; ws.close(); ws = null; }

  ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => postMessage({ type: 'ws-open' });

  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer && audioPort) {
      audioPort.postMessage(e.data, [e.data]);
    }
  };

  ws.onclose = () => {
    postMessage({ type: 'ws-close' });
    ws = null;
    reconnectTimer = setTimeout(connect, 3000);
  };

  ws.onerror = () => { if (ws) ws.close(); };
}

onmessage = (e) => {
  const msg = e.data;
  if (msg.type === 'init') {
    wsUrl = msg.url;
    audioPort = msg.port;
    connect();
  } else if (msg.type === 'stop') {
    clearTimeout(reconnectTimer);
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    audioPort = null;
    close();
  }
};
`;

type AudioState = 'stopped' | 'starting' | 'running' | 'error';

interface UseAudioPlayerReturn {
  start: () => Promise<void>;
  stop: () => void;
  setVolume: (v: number) => void;
  state: AudioState;
}

const LOG_PREFIX = '[AudioPlayer]';

function logWarn(...args: unknown[]) {
  console.warn(LOG_PREFIX, ...args);
}


export function useAudioPlayer(audioWsUrl?: string): UseAudioPlayerReturn {
  const ctxRef = useRef<AudioContext | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const gainRef = useRef<GainNode | null>(null);
  const workerRef = useRef<Worker | null>(null);
  const volumeRef = useRef(0.5);
  const stateRef = useRef<AudioState>('stopped');
  const [stateForRender, setStateForRender] = useState<AudioState>('stopped');

  useEffect(() => {
    return () => stopInternal();
  }, []);

  function stopInternal() {
    if (workerRef.current) {
      workerRef.current.postMessage({ type: 'stop' });
      workerRef.current.terminate();
      workerRef.current = null;
    }
    if (workletRef.current) {
      workletRef.current.disconnect();
      workletRef.current = null;
    }
    if (gainRef.current) {
      gainRef.current.disconnect();
      gainRef.current = null;
    }
    if (ctxRef.current) {
      ctxRef.current.close().catch(() => {});
      ctxRef.current = null;
    }
    stateRef.current = 'stopped';
    setStateForRender('stopped');
  }

  const start = useCallback(async () => {
    if (stateRef.current === 'running' || stateRef.current === 'starting') return;

    stateRef.current = 'starting';
    setStateForRender('starting');

    try {
      const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      ctxRef.current = ctx;

      // Load worklet from blob URL
      const workletBlob = new Blob([WORKLET_CODE], { type: 'application/javascript' });
      const workletUrl = URL.createObjectURL(workletBlob);
      await ctx.audioWorklet.addModule(workletUrl);
      URL.revokeObjectURL(workletUrl);

      const worklet = new AudioWorkletNode(ctx, 'pcm-processor', {
        outputChannelCount: [1],
      });
      workletRef.current = worklet;

      worklet.port.onmessage = (e) => {
        if (e.data.type === 'underrun') {
          logWarn(`buffer underrun #${e.data.count} (buffered: ${e.data.buffered})`);
        }
      };

      // Gain node for volume control
      const gain = ctx.createGain();
      gain.gain.value = volumeRef.current;
      gainRef.current = gain;

      worklet.connect(gain);
      gain.connect(ctx.destination);

      if (ctx.state === 'suspended') await ctx.resume();

      // Set up Worker + MessageChannel for off-main-thread audio delivery
      if (audioWsUrl) {
        const channel = new MessageChannel();
        // port1 → worklet (receives audio), port2 → worker (sends audio)
        worklet.port.postMessage({ type: 'audio-port', port: channel.port1 }, [channel.port1]);

        const workerBlob = new Blob([WORKER_CODE], { type: 'application/javascript' });
        const workerUrl = URL.createObjectURL(workerBlob);
        const worker = new Worker(workerUrl);
        URL.revokeObjectURL(workerUrl);
        workerRef.current = worker;

        worker.onmessage = (e) => {
          if (e.data.type === 'ws-close') logWarn('audio WS disconnected');
        };

        worker.postMessage({ type: 'init', url: audioWsUrl, port: channel.port2 }, [channel.port2]);
      }

      stateRef.current = 'running';
      setStateForRender('running');
    } catch (err) {
      console.error(LOG_PREFIX, 'failed to start:', err);
      stateRef.current = 'error';
      setStateForRender('error');
      stopInternal();
    }
  }, [audioWsUrl]);

  const stop = useCallback(() => stopInternal(), []);

  const setVolume = useCallback((v: number) => {
    const clamped = Math.max(0, Math.min(1, v));
    volumeRef.current = clamped;
    if (gainRef.current) {
      gainRef.current.gain.value = clamped;
    }
  }, []);

  return {
    start,
    stop,
    setVolume,
    state: stateForRender,
  };
}
