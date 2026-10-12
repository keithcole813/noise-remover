#!/usr/bin/env python3
"""
Noise Remover — web version.

Run on your home server, open from your phone's browser, upload a video,
and get back the same video with AI-cleaned audio (DeepFilterNet).

Setup:
  pip install -r requirements.txt     # pulls torch + deepfilternet (one-time, ~200MB)
  python web_app.py                   # serves on port 5002

  # from outside your network:
  cloudflared tunnel --url http://localhost:5002

Optional:
  DENOISE_PASSWORD=secret python web_app.py   # lock it with a password
"""
import glob
import os
import shutil
import subprocess
import threading
import time
import uuid

from flask import Flask, jsonify, render_template_string, request, send_file

PORT = int(os.environ.get("PORT", 5002))
BASE_DIR = os.path.expanduser("~/denoise-jobs")
PASSWORD = os.environ.get("DENOISE_PASSWORD", "")
MAX_AGE = 24 * 3600
MAX_UPLOAD = 2 * 1024 * 1024 * 1024  # 2 GB

os.makedirs(BASE_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD

jobs = {}
jobs_lock = threading.Lock()

# DeepFilterNet model loads once at startup (slow first time: downloads model).
_df = {}


def get_df():
    if "model" not in _df:
        from df.enhance import init_df
        model, df_state, _ = init_df()
        _df["model"] = model
        _df["state"] = df_state
    return _df["model"], _df["state"]


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Noise Remover</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0b0f1a; color:#f1f5f9;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         min-height:100vh; display:flex; flex-direction:column; align-items:center;
         padding:2.5rem 1.25rem; }
  h1 { font-size:1.8rem; margin-bottom:.3rem; }
  .sub { color:#94a3b8; margin-bottom:2rem; font-size:.95rem; text-align:center; }
  .box { width:100%; max-width:480px; }
  label.lbl { display:block; font-size:.85rem; font-weight:600; color:#cbd5e1; margin:0 0 .35rem; }
  input[type=password] { width:100%; background:#141b2e; border:1px solid #26314d;
          border-radius:12px; color:#f1f5f9; padding:1rem; font-size:1rem; margin-bottom:1rem; }
  input[type=password]:focus { outline:none; border-color:#f0cd6e; }
  .filepick { display:block; width:100%; background:#141b2e; border:2px dashed #26314d;
              border-radius:12px; padding:2rem 1rem; text-align:center; color:#94a3b8;
              font-size:1rem; margin-bottom:1rem; cursor:pointer; }
  .filepick.picked { border-color:#f0cd6e; color:#f1f5f9; }
  input[type=file] { display:none; }
  #go { width:100%; background:#f0cd6e; color:#0b0f1a; border:none; border-radius:12px;
        font-size:1.15rem; font-weight:800; padding:1.1rem; }
  #go:disabled { opacity:.5; }
  #prog-wrap { margin-top:1.5rem; display:none; }
  .bar { height:14px; background:#141b2e; border-radius:999px; overflow:hidden; border:1px solid #26314d; }
  .bar > div { height:100%; width:0%; background:#38bdf8; border-radius:999px; transition:width .3s; }
  #status { margin-top:.7rem; color:#94a3b8; font-size:.95rem; text-align:center; }
  #save { display:none; margin-top:1.2rem; width:100%; background:#10b981; color:#06281c;
          text-align:center; text-decoration:none; font-weight:800; font-size:1.15rem;
          padding:1.1rem; border-radius:12px; }
  #err { display:none; margin-top:1rem; color:#f87171; font-size:.9rem; text-align:center;
         word-break:break-word; }
  .hint { margin-top:2.5rem; color:#475569; font-size:.8rem; text-align:center; line-height:1.7; }
</style>
</head>
<body>
  <h1>&#129689; Noise Remover</h1>
  <p class="sub">Upload a video. Get it back with clean audio.</p>
  <div class="box">
    <div id="pw-row" style="display:none">
      <label class="lbl" for="pw">Password</label>
      <input id="pw" type="password" placeholder="••••••••">
    </div>
    <label class="filepick" id="pick" for="file">Tap to choose a video</label>
    <input id="file" type="file" accept="video/*">
    <button id="go" disabled>Clean the audio</button>
    <div id="prog-wrap">
      <div class="bar"><div id="fill"></div></div>
      <div id="status">Uploading…</div>
    </div>
    <a id="save" href="#">&#11015; Save clean video</a>
    <div id="err"></div>
    <p class="hint">AI removes background noise, hum &amp; hiss.<br>Your video never leaves your server.</p>
  </div>
<script>
const $ = id => document.getElementById(id);
let pwRequired = false, jobId = null;

async function init() {
  try {
    const cfg = await (await fetch('/api/config')).json();
    pwRequired = cfg.password_required;
    if (pwRequired) {
      $('pw-row').style.display = 'block';
      $('pw').value = localStorage.getItem('dn_pw') || '';
    }
  } catch(e) {}
}
init();

$('file').onchange = () => {
  const f = $('file').files[0];
  if (f) {
    $('pick').textContent = f.name + ' (' + (f.size/1048576).toFixed(1) + ' MB)';
    $('pick').classList.add('picked');
    $('go').disabled = false;
  }
};

$('go').onclick = () => {
  const f = $('file').files[0];
  if (!f) return;
  const password = pwRequired ? $('pw').value : '';
  if (pwRequired) localStorage.setItem('dn_pw', password);
  $('go').disabled = true; hideErr();
  $('save').style.display = 'none';
  $('prog-wrap').style.display = 'block';
  setBar(0); setStatus('Uploading… 0%');

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/upload');
  xhr.upload.onprogress = e => {
    if (e.lengthComputable) {
      const p = e.loaded / e.total * 100;
      setBar(p); setStatus('Uploading… ' + p.toFixed(0) + '%');
    }
  };
  xhr.onload = () => {
    let data = {};
    try { data = JSON.parse(xhr.responseText); } catch(e) {}
    if (xhr.status !== 200) {
      showErr(data.error || 'Upload failed.');
      $('go').disabled = false; $('prog-wrap').style.display = 'none';
      return;
    }
    jobId = data.job_id;
    poll();
  };
  xhr.onerror = () => {
    showErr('Upload failed — check your connection.');
    $('go').disabled = false; $('prog-wrap').style.display = 'none';
  };
  const fd = new FormData();
  fd.append('video', f);
  fd.append('password', password);
  xhr.send(fd);
};

function setBar(p){ $('fill').style.width = p + '%'; }
function setStatus(t){ $('status').textContent = t; }
function showErr(t){ const e=$('err'); e.textContent=t; e.style.display='block'; }
function hideErr(){ $('err').style.display='none'; }

async function poll() {
  try {
    const j = await (await fetch('/api/status/' + jobId)).json();
    const labels = {extracting:'Pulling out the audio…', denoising:'Removing background noise…',
                    muxing:'Putting the video back together…', done:'Done.'};
    if (j.state === 'done') {
      setBar(100); setStatus('Done.');
      const s = $('save');
      s.href = '/api/file/' + jobId;
      s.style.display = 'block';
      $('go').disabled = false;
      return;
    }
    if (j.state === 'error') {
      showErr('Failed: ' + (j.error || 'unknown error'));
      $('prog-wrap').style.display = 'none';
      $('go').disabled = false;
      return;
    }
    setBar(j.state === 'extracting' ? 12 : j.state === 'denoising' ? 55 : 88);
    setStatus(labels[j.state] || 'Working…');
    setTimeout(poll, 1500);
  } catch(e) { setTimeout(poll, 2500); }
}
</script>
</body>
</html>
"""


def set_state(job_id, **kw):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kw)


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def process_worker(job_id, src_path, orig_name):
    job_dir = os.path.join(BASE_DIR, job_id)
    wav_in = os.path.join(job_dir, "audio_in.wav")
    wav_clean = os.path.join(job_dir, "audio_clean.wav")
    out_path = os.path.join(job_dir, "clean_" + orig_name)
    try:
        # 1. extract audio as 48kHz mono wav
        set_state(job_id, state="extracting")
        run(["ffmpeg", "-y", "-i", src_path,
             "-vn", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", wav_in])

        # 2. AI denoise
        set_state(job_id, state="denoising")
        from df.enhance import load_audio, save_audio, enhance
        model, df_state = get_df()
        audio, _ = load_audio(wav_in, sr=df_state.sr())
        enhanced = enhance(model, df_state, audio)
        save_audio(wav_clean, enhanced, df_state.sr())

        # 3. mux clean audio back onto original video
        set_state(job_id, state="muxing")
        run(["ffmpeg", "-y", "-i", src_path, "-i", wav_clean,
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-map", "0:v:0", "-map", "1:a:0", "-shortest", out_path])

        set_state(job_id, state="done", path=out_path,
                  filename="clean_" + orig_name)
    except subprocess.CalledProcessError as e:
        set_state(job_id, state="error",
                  error="ffmpeg failed: " + (e.stderr or b"")[:200].decode("utf8", "ignore"))
    except Exception as e:
        set_state(job_id, state="error", error=str(e)[:300])


@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/api/config")
def config():
    return jsonify({"password_required": bool(PASSWORD)})


@app.route("/api/upload", methods=["POST"])
def upload():
    if PASSWORD and request.form.get("password") != PASSWORD:
        return jsonify({"error": "Wrong password."}), 403
    f = request.files.get("video")
    if not f or not f.filename:
        return jsonify({"error": "No video received."}), 400
    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(BASE_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    # keep a filesystem-safe name
    safe = "".join(c for c in f.filename if c.isalnum() or c in "._- ")[:80].strip()
    if not safe:
        safe = "video.mp4"
    src_path = os.path.join(job_dir, "src_" + safe)
    f.save(src_path)
    with jobs_lock:
        jobs[job_id] = {"state": "extracting", "created": time.time()}
    threading.Thread(target=process_worker, args=(job_id, src_path, safe),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "unknown job"}), 404
        job = dict(job)
    job.pop("path", None)
    return jsonify(job)


@app.route("/api/file/<job_id>")
def get_file(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or job.get("state") != "done" or not job.get("path"):
        return jsonify({"error": "not ready"}), 404
    return send_file(job["path"], as_attachment=True,
                     download_name=job.get("filename", "clean_video.mp4"))


def cleanup_loop():
    while True:
        time.sleep(1800)
        now = time.time()
        with jobs_lock:
            stale = [jid for jid, j in jobs.items()
                     if now - j.get("created", now) > MAX_AGE]
            for jid in stale:
                jobs.pop(jid, None)
        for jid in stale:
            shutil.rmtree(os.path.join(BASE_DIR, jid), ignore_errors=True)


if __name__ == "__main__":
    print("Loading DeepFilterNet model (first run downloads it)…")
    get_df()
    print("Model ready.")
    threading.Thread(target=cleanup_loop, daemon=True).start()
    # NOTE: front this with cloudflared for outside access; keep it on localhost.
    app.run(host="127.0.0.1", port=PORT)
