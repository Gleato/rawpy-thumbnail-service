import os
import tempfile
import requests
from flask import Flask, request, jsonify
import rawpy
import imageio.v2 as imageio

app = Flask(__name__)

@app.route("/generate-thumbnail", methods=["POST"])
def generate_thumbnail():
    data = request.get_json()
    raw_url = data.get("rawFileUrl")
    upload_url = data.get("uploadUrl")

    if not raw_url or not upload_url:
        return jsonify({"error": "Missing rawFileUrl or uploadUrl"}), 400

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "input.dng")
            jpeg_path = os.path.join(tmpdir, "output.jpg")

            # Download RAW image
            with requests.get(raw_url, stream=True) as r:
                r.raise_for_status()
                with open(raw_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            # Convert RAW to RGB and save as JPEG
            with rawpy.imread(raw_path) as raw:
                rgb = raw.postprocess()
                imageio.imwrite(jpeg_path, rgb)

            # Upload to Convex
            with open(jpeg_path, "rb") as f:
                upload_res = requests.post(upload_url, data=f, headers={
                    "Content-Type": "image/jpeg"
                })

            if upload_res.status_code != 200:
                raise Exception(f"Upload failed: {upload_res.text}")

            storage_id = upload_res.json().get("storageId")
            if not storage_id:
                raise Exception("No storageId returned by Convex")

            return jsonify({
                "success": True,
                "storageId": storage_id
            })

    except Exception as e:
        print("❌ Error:", e)
        return jsonify({
            "error": str(e),
            "details": "RAW to JPEG conversion failed."
        }), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# ✅ Required for Render: bind to 0.0.0.0 and use the PORT env var
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
