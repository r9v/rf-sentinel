# RFSentinel

**Open-source RF spectrum monitoring & signal classification platform**

RTL-SDR based tool for real-time RF spectrum analysis, signal detection, and automatic classification.

## Quick Start

```bash
# Install Python dependencies
pip install -r requirements.txt

# Start the backend
python -m core.api.server --demo    # demo mode (no SDR needed)
python -m core.api.server           # live mode (SDR required)

# In a second terminal, start the frontend
cd frontend
npm install
npm run dev

# Open http://localhost:5173
```

## Requirements

- **Hardware:** RTL-SDR Blog V4 (or compatible) — not needed for demo mode
- **OS:** Windows 10/11, Linux
- **Python:** 3.10+
- **Node.js:** 18+ (for frontend)

## Project Structure

```
rf-sentinel/
├── core/                   Python package
│   ├── __init__.py         Package root, version string
│   ├── cli.py              CLI interface (scan, waterfall, sweep commands)
│   ├── plotting.py         Matplotlib rendering + BANDS frequency presets
│   ├── sdr/                SDR hardware interface
│   │   └── __init__.py     SDRDevice wrapper, CaptureConfig, CaptureResult
│   ├── dsp/                Digital signal processing
│   │   └── __init__.py     PSD (Welch method), spectrogram/waterfall generation
│   └── api/                FastAPI backend for the web dashboard
│       ├── models.py       Pydantic request/response schemas
│       ├── runner.py       Background job executor with demo mode
│       └── server.py       REST + WebSocket server, log streaming
├── frontend/               React + Vite + Tailwind dashboard
│   └── src/
│       ├── App.tsx          Main layout
│       ├── api.ts           API client
│       ├── hooks/           WebSocket hook for live log streaming
│       └── components/      ControlPanel, LogConsole, JobList, ResultView
├── pyproject.toml
├── requirements.txt
└── README.md
```

### Core Modules

**`core/sdr/`** — SDR hardware interface. `SDRDevice` is a context manager wrapping `pyrtlsdr`. Handles device configuration, PLL settling (discards first chunk), and memory-safe chunked I/Q capture. `CaptureConfig` and `CaptureResult` dataclasses carry parameters and samples.

**`core/dsp/`** — Signal processing. `compute_psd` runs Welch's method for power spectral density (frequency vs power). `compute_waterfall` generates spectrograms (frequency vs time vs power). Both return typed result objects with frequencies in MHz and power in dB.

**`core/plotting.py`** — Matplotlib rendering for spectrum and waterfall plots. Defines the `BANDS` dictionary with predefined frequency presets: FM Radio, Airband, PMR446, 433 MHz IoT, 868 MHz LoRa, GSM 900, and ADS-B.

**`core/cli.py`** — Command-line interface with three commands: `scan` (single-band PSD), `waterfall` (spectrogram), and `sweep` (all bands sequentially).

**`core/api/`** — FastAPI backend powering the web dashboard. REST endpoints to launch scan/waterfall/sweep jobs, WebSocket endpoint for real-time log streaming, background thread pool for job execution (one at a time — single SDR dongle), and a demo mode that generates synthetic RF data for development without hardware.

### Data Flow

Frontend clicks **Run** → `POST /api/scan` → runner queues a `Job` → background thread calls `sdr` → `dsp` processes samples → dark-themed plot rendered to PNG → job marked complete → frontend polls `/api/jobs` and displays the image. Logs stream live via WebSocket throughout.

## License

MIT
