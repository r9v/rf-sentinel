import { useRef, useState, useCallback, useEffect } from 'react';

// AudioWorklet processor — runs in audio thread, reads from ring buffer
const WORKLET_CODE = `
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ring = new Float32Array(48000 * 2); // 2s max buffer
    this._writePos = 0;
    this._readPos = 0;
    this._count = 0;       // samples available
    this._underruns = 0;

    this.port.onmessage = (e) => {
      const samples = e.data;
      const ring = this._ring;
      const len = ring.length;

      for (let i = 0; i < samples.length; i++) {
        ring[this._writePos] = samples[i];
        this._writePos = (this._writePos + 1) % len;
      }
      this._count = Math.min(this._count + samples.length, len);
    };
  }

  process(inputs, outputs) {
    const out = outputs[0][0]; // mono, 128 samples
    if (!out) return true;
    const needed = out.length;
    const ring = this._ring;
    const len = ring.length;

    if (this._count >= needed) {
      for (let i = 0; i < needed; i++) {
        out[i] = ring[this._readPos];
        this._readPos = (this._readPos + 1) % len;
      }
      this._count -= needed;
    } else {
      // Underrun — output silence
      out.fill(0);
      this._underruns++;
      if (this._underruns % 100 === 1) {
        this.port.postMessage({ type: 'underrun', count: this._underruns, buffered: this._count });
      }
    }

    // Periodic status report
    if (currentFrame % 12000 === 0) {
      this.port.postMessage({ type: 'status', buffered: this._count, underruns: this._underruns });
    }

    return true;
  }
}
registerProcessor('pcm-processor', PCMProcessor);
`;

type AudioState = 'stopped' | 'starting' | 'running' | 'error';

interface UseAudioPlayerReturn {
  feedAudio: (data: ArrayBuffer) => void;
  start: () => Promise<void>;
  stop: () => void;
  setVolume: (v: number) => void;
  state: AudioState;
}

const LOG_PREFIX = '[AudioPlayer]';

function log(...args: unknown[]) {
  console.log(LOG_PREFIX, ...args);
}

function logWarn(...args: unknown[]) {
  console.warn(LOG_PREFIX, ...args);
}

function int16ToFloat32(buffer: ArrayBuffer): Float32Array {
  const int16 = new Int16Array(buffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 32768;
  }
  return float32;
}

export function useAudioPlayer(): UseAudioPlayerReturn {
  const ctxRef = useRef<AudioContext | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const gainRef = useRef<GainNode | null>(null);
  const stateRef = useRef<AudioState>('stopped');
  const [stateForRender, setStateForRender] = useState<AudioState>('stopped');

  // Clean up on unmount
  useEffect(() => {
    return () => {
      log('unmounting, cleaning up');
      stopInternal();
    };
  }, []);

  function stopInternal() {
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
    if (stateRef.current === 'running' || stateRef.current === 'starting') {
      log('already', stateRef.current);
      return;
    }

    stateRef.current = 'starting';
    setStateForRender('starting');
    log('initializing AudioContext @ 48kHz');

    try {
      const ctx = new AudioContext({ sampleRate: 48000 });
      ctxRef.current = ctx;

      // Load worklet from blob URL
      const blob = new Blob([WORKLET_CODE], { type: 'application/javascript' });
      const url = URL.createObjectURL(blob);
      log('loading worklet module');
      await ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);

      // Create worklet node (mono output)
      const worklet = new AudioWorkletNode(ctx, 'pcm-processor', {
        outputChannelCount: [1],
      });
      workletRef.current = worklet;

      // Listen for status messages from worklet
      worklet.port.onmessage = (e) => {
        const msg = e.data;
        if (msg.type === 'underrun') {
          logWarn(`buffer underrun #${msg.count} (buffered: ${msg.buffered})`);
        } else if (msg.type === 'status') {
          const ms = ((msg.buffered / 48000) * 1000).toFixed(0);
          log(`worklet status: ${ms}ms buffered, ${msg.underruns} underruns`);
        }
      };

      // Gain node for volume control
      const gain = ctx.createGain();
      gain.gain.value = 0.5;
      gainRef.current = gain;

      // Connect: worklet → gain → speakers
      worklet.connect(gain);
      gain.connect(ctx.destination);

      // Resume context (required after user gesture)
      if (ctx.state === 'suspended') {
        log('resuming suspended AudioContext');
        await ctx.resume();
      }

      stateRef.current = 'running';
      setStateForRender('running');
      log(`started: sampleRate=${ctx.sampleRate} state=${ctx.state}`);
    } catch (err) {
      console.error(LOG_PREFIX, 'failed to start:', err);
      stateRef.current = 'error';
      setStateForRender('error');
      stopInternal();
    }
  }, []);

  const stop = useCallback(() => {
    log('stopping');
    stopInternal();
  }, []);

  const feedAudio = useCallback((data: ArrayBuffer) => {
    if (!workletRef.current || stateRef.current !== 'running') return;
    const float32 = int16ToFloat32(data);
    workletRef.current.port.postMessage(float32, [float32.buffer]);
  }, []);

  const setVolume = useCallback((v: number) => {
    if (gainRef.current) {
      const clamped = Math.max(0, Math.min(1, v));
      gainRef.current.gain.value = clamped;
      log('volume →', clamped.toFixed(2));
    }
  }, []);

  return {
    feedAudio,
    start,
    stop,
    setVolume,
    state: stateForRender,
  };
}
