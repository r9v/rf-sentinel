# RFSentinel

**Open-source RF spectrum monitoring & signal classification platform**

RTL-SDR based tool for real-time RF spectrum analysis, signal detection, and automatic classification.

![RFSentinel scanning the FM broadcast band](showcase1.png)
![RFSentinel signal detection](showcase2.png)

## Quick Start

```bash
# Install Python dependencies
pip install -r requirements.txt

# Start the backend (SDR required)
python -m core.api.server

# In a second terminal, start the frontend
cd frontend
npm install
npm run dev

# Open http://localhost:5173
```

## Requirements

- **Hardware:** RTL-SDR Blog V4 (or compatible)
- **OS:** Windows 10/11, Linux
- **Python:** 3.10+
- **Node.js:** 18+ (for frontend)

## Features

### Live Mode

Continuous real-time spectrum display with signal detection:

- Live-updating power spectrum with scrolling waterfall spectrogram
- Max-hold trace (decaying peak envelope)
- Temporal PSD smoothing (EMA) for stable display and better weak-signal visibility
- Peak tracking across frames with confirmation logic — eliminates jitter
- Click-to-tune VFO marker with draggable repositioning
- FM/AM audio demodulation streamed as PCM over WebSocket
- Drag-to-pan and scroll-to-zoom on the frequency axis
- Dual-thumb range sliders for both axes

### Scan Mode

Captures a spectrum + waterfall over a frequency range, stitching multiple chunks for wide sweeps (>1.6 MHz bandwidth per chunk, 80% usable with edge trimming). Full-resolution 1D spectrum with decimated 2D waterfall for web delivery.

### Signal Detection

Adaptive noise floor estimation with threshold-then-segment peak finding:

- Rolling 25th-percentile filter (501-bin window) — robust in dense signal environments
- Contiguous above-threshold regions merged across small gaps (≤50 kHz), capped at 300 kHz bandwidth
- Max-hold peak detection: runs find_peaks on max PSD from waterfall to catch brief/intermittent transmissions missed by time-averaged spectrum
- Auto-scaling peak limit based on scan bandwidth (5 peaks/MHz)
- Peaks ranked by SNR (prominence above local noise floor)

### Signal Classification

Rule-based spectral classification with band-aware confidence adjustment:

- Spectral features: flatness, occupied bandwidth (99% power), edge steepness
- Temporal features from waterfall: duty cycle (fraction of time active) and power variance to distinguish bursty voice comms from continuous broadcasts
- Types: FM broadcast, narrowband FM, AM, digital, carrier/CW, aviation, ham, ISM, GSM, ADS-B
- Band database (12 entries): FM/AM broadcast, airband, ham bands, PMR446, ISM 433/868, GSM 900, ADS-B
- Band prior promotes narrowband detections to band-specific types (e.g. NFM on airband → aviation)

### Frontend

- uPlot-based spectrum chart with colored peak markers per signal type
- Signal list sidebar — sortable, color-coded, click to tune
- Waterfall spectrogram with contrast slider
- Preset buttons for common bands (FM, airband, ham, ISM)
- Real-time log console and job history via WebSocket

## License

MIT
