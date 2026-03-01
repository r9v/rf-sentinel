# RFSentinel

**Open-source RF spectrum monitoring & signal classification platform**

RTL-SDR based tool for real-time RF spectrum analysis, signal detection, and automatic classification.

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

### Scan

Single-shot power spectral density capture across a frequency range. Uses Welch's method to compute power (dB) vs frequency (MHz). Results render as an interactive chart with peak detection markers and configurable x/y axis ranges.

### Waterfall

Spectrogram capture showing frequency vs time vs power. Produces a heatmap image where the x-axis is frequency, y-axis is time, and color intensity represents signal power. Useful for spotting intermittent or hopping signals.

### Live Mode

Continuous real-time spectrum display. The SDR streams I/Q samples and the frontend renders a live-updating power spectrum with:
- Max-hold trace (decaying peak envelope)
- Click-to-tune VFO marker with draggable repositioning
- Drag-to-pan and scroll-to-zoom on the frequency axis
- Dual-thumb range sliders for both axes
- dB range markers showing min/max power over a 30-second sliding window

### Audio Demodulation

When live mode is active, click a frequency to tune the VFO and enable audio output. Supports FM demodulation streamed over a dedicated WebSocket as PCM audio, played back in the browser via the Web Audio API with adjustable volume.

## License

MIT
