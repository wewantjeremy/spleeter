import os
import glob
import subprocess
import tempfile
import numpy as np
import librosa
import soundfile as sf
from flask import Blueprint, request, jsonify, send_file
from database import SessionLocal
from models import Song

bp = Blueprint("main", __name__)

SEPARATED_DIR = "separated"
DOWNLOADS_DIR = "downloads"


@bp.route("/")
def index():
    return open("index.html").read()


@bp.route("/split", methods=["POST"])
def split():
    url = request.form.get("url")
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    db = SessionLocal()
    song = Song(youtube_url=url, status="processing")
    db.add(song)
    db.commit()

    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        os.makedirs(SEPARATED_DIR, exist_ok=True)

        # Download audio and capture title in one pass
        output_template = os.path.join(DOWNLOADS_DIR, f"{song.id}.%(ext)s")
        # Fetch title separately so stdout is unambiguous
        title_result = subprocess.run(
            ["yt-dlp", "--print", "title", "--no-download",
             url],
            capture_output=True, text=True, check=True
        )
        song.title = title_result.stdout.strip()
        db.commit()

        subprocess.run(
            ["yt-dlp", "-x", "--audio-format", "wav", "-o", output_template,
             url],
            capture_output=True, text=True, check=True
        )

        files = glob.glob(os.path.join(DOWNLOADS_DIR, f"{song.id}.*"))
        if not files:
            raise Exception("Download failed — no file found")
        audio_file = files[0]

        # Run demucs (6-stem model: vocals, drums, bass, guitar, piano, other)
        subprocess.run(
            ["demucs", "-n", "htdemucs_6s", "-o", SEPARATED_DIR, audio_file],
            check=True
        )

        track_name = os.path.splitext(os.path.basename(audio_file))[0]
        output_dir = os.path.join(SEPARATED_DIR, "htdemucs_6s", track_name)

        song.status = "done"
        song.output_dir = output_dir
        db.commit()

        return jsonify({
            "id": song.id,
            "title": song.title,
            "stems": {s: f"/stems/{song.id}/{s}" for s in ["vocals", "drums", "bass", "guitar", "piano", "other"]}
        })

    except Exception as e:
        song.status = "error"
        db.commit()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@bp.route("/stems/<int:song_id>/<stem>")
def get_stem(song_id, stem):
    if stem not in {"vocals", "drums", "bass", "guitar", "piano", "other"}:
        return "Invalid stem", 400

    db = SessionLocal()
    song = db.query(Song).get(song_id)
    db.close()

    if not song or song.status != "done":
        return "Not found", 404

    path = os.path.join(song.output_dir, f"{stem}.wav")

    try:
        semitones = float(request.args.get("semitones", 0))
    except ValueError:
        semitones = 0

    safe_title = "".join(c if c not in '/\\:*?"<>|' else "_" for c in song.title or "song")

    if semitones == 0:
        return send_file(
            path,
            as_attachment=True,
            download_name=f"{safe_title}_{stem}.wav"
        )
    y, sr = librosa.load(path, sr=None, mono=False)
    if y.ndim == 1:
        shifted = librosa.effects.pitch_shift(y, sr=sr, n_steps=semitones)
    else:
        shifted = np.stack([
            librosa.effects.pitch_shift(channel, sr=sr, n_steps=semitones)
            for channel in y
        ])

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()

    sf.write(tmp.name, shifted.T if shifted.ndim > 1 else shifted, sr)
    
    response = send_file(
        tmp.name,
        as_attachment=True,
        download_name=f"{safe_title}_{stem}_shifted{int(semitones):+d}.wav"
)

    os.unlink(tmp.name)

    return response