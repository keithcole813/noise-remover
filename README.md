# Noise Remover

Upload a video from your phone, get it back with AI-cleaned audio. Built
to replace a CapCut paywall — background noise, hum, and hiss removed with
[DeepFilterNet](https://github.com/Rikorose/DeepFilterNet), right on your
own server. Your videos never leave your machine.

## How it works

1. Phone uploads the video
2. Server extracts the audio track
3. DeepFilterNet (AI) removes background noise
4. Clean audio is muxed back onto the original video
5. Phone downloads the finished video

## Setup (home server)

1. Install Python 3 (3.9+) and **ffmpeg**:
   - Linux Mint: `sudo apt install ffmpeg`
2. Install Rust (one-time — DeepFilterNet has Rust extensions to compile):
   ```
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```
   Then restart your terminal (or `source ~/.cargo/env`).
3. Install dependencies in a virtual environment:
   ```
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   # torch must match DeepFilterNet's torchaudio — install the CPU builds:
   pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
   ```
   (First run downloads the AI model, ~8MB, and may take a minute to load.)
4. Run it:
   ```
   python web_app.py        # serves on port 5002
   ```
4. From outside your network:
   ```
   cloudflared tunnel --url http://localhost:5002
   ```

Open the page on your phone, tap to pick a video, and hit "Clean the audio."

## Options

- Password lock: `DENOISE_PASSWORD=secret python web_app.py`
- iPhone tip: Share → Add to Home Screen and it feels like a real app

Uploads and finished videos are cleaned up automatically after 24 hours.
