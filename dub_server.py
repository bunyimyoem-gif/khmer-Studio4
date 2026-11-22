import os, json, uuid, asyncio, subprocess, tempfile
import edge_tts
from flask import Flask, request, send_file, jsonify

app = Flask(__name__)

@app.after_request
def add_cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r

ROLE_MAP = {
    "male": ("km-KH-PisethNeural", "+0%", "-2Hz"),
    "female": ("km-KH-SreymomNeural", "+0%", "+0Hz"),
    "boy": ("km-KH-PisethNeural", "+10%", "+6Hz"),
    "girl": ("km-KH-SreymomNeural", "+8%", "+8Hz"),
    "oldm": ("km-KH-PisethNeural", "-8%", "-6Hz"),
    "oldw": ("km-KH-SreymomNeural", "-8%", "-3Hz"),
    "": ("km-KH-PisethNeural", "+0%", "+0Hz"),
}

async def synth_line(text, role, out_mp3):
    voice, rate, pitch = ROLE_MAP.get(role or "", ROLE_MAP[""])
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(out_mp3)

@app.post("/api/dub")
def api_dub():
    payload = json.loads(request.form.get("payload") or "{}")
    cues = [c for c in (payload.get("cues") or []) if (c.get("text") or "").strip()]
    keep_bg = bool(payload.get("keep_bg", True))
    if not cues:
        return jsonify(error="No cues"), 400

    with tempfile.TemporaryDirectory() as td:
        mp3_list = []
        for idx, c in enumerate(cues):
            p = os.path.join(td, f"line_{idx}.mp3")
            asyncio.run(synth_line(c["text"].strip(), c.get("role", ""), p))
            mp3_list.append((float(c.get("start", 0)), p))

        concat_txt = os.path.join(td, "list.txt")
        with open(concat_txt, "w", encoding="utf-8") as f:
            for _, p in mp3_list:
                f.write(f"file '{p.replace(chr(92), '/')}'\n")

        voice_track = os.path.join(td, "khmer_voice.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c:a", "libmp3lame", "-q:a", "3", voice_track],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        vid_file = request.files.get("video")
        if not vid_file:
            out_audio = os.path.join(td, "out.mp3")
            subprocess.run(["ffmpeg", "-y", "-i", voice_track, "-c", "copy", out_audio], check=True)
            return send_file(out_audio, mimetype="audio/mpeg", as_attachment=True, download_name="khmer_dub.mp3")

        in_vid = os.path.join(td, f"in_{uuid.uuid4().hex[:6]}.mp4")
        vid_file.save(in_vid)
        out_vid = os.path.join(td, "out.mp4")

        if keep_bg:
            cmd = [
                "ffmpeg", "-y", "-i", in_vid, "-i", voice_track,
                "-filter_complex", "[0:a]volume=0.18[bg];[1:a]volume=1.3[vo];[bg][vo]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out_vid
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", in_vid, "-i", voice_track,
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_vid
            ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return send_file(out_vid, mimetype="video/mp4", as_attachment=True, download_name="khmer_dub.mp4")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
