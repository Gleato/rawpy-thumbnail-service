import os
import tempfile
import requests
from flask import Flask, request, jsonify
import rawpy
from PIL import Image
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

            logger.info(f"Processing RAW file from: {raw_url}")

            # Download RAW image with timeout
            with requests.get(raw_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                file_size = 0
                with open(raw_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                        file_size += len(chunk)
                        # Prevent extremely large files (>100MB)
                        if file_size > 100 * 1024 * 1024:
                            raise Exception("File too large (>100MB)")

            logger.info(f"Downloaded RAW file: {file_size} bytes")

            # Convert RAW to RGB with optimized settings
            with rawpy.imread(raw_path) as raw:
                # Use faster processing settings for thumbnails
                rgb = raw.postprocess(
                    use_camera_wb=True,           # Faster than auto WB
                    half_size=True,               # Process at half resolution for speed
                    dcb_iterations=1,             # Reduce demosaicing iterations
                    output_bps=8                  # 8-bit output is sufficient for thumbnails
                )
                
                # Convert to PIL Image for resizing
                img = Image.fromarray(rgb)
                
                # Calculate thumbnail size maintaining aspect ratio
                original_width, original_height = img.size
                target_width, target_height = 800, 600
                
                # Calculate scaling to fit within bounds
                width_ratio = target_width / original_width
                height_ratio = target_height / original_height
                scale_ratio = min(width_ratio, height_ratio)
                
                new_width = int(original_width * scale_ratio)
                new_height = int(original_height * scale_ratio)
                
                # Resize with high-quality resampling
                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Save as JPEG with optimized settings
                img_resized.save(
                    jpeg_path, 
                    'JPEG', 
                    quality=100,                   # Good quality/size balance
                    optimize=True,                # Enable JPEG optimization
                    progressive=True              # Progressive JPEG for web
                )

            # Get file size for logging
            jpeg_size = os.path.getsize(jpeg_path)
            logger.info(f"Generated thumbnail: {new_width}x{new_height}, {jpeg_size} bytes")

            # Upload to Convex with timeout
            with open(jpeg_path, "rb") as f:
                upload_res = requests.post(
                    upload_url, 
                    data=f, 
                    headers={"Content-Type": "image/jpeg"},
                    timeout=30
                )

            if upload_res.status_code != 200:
                raise Exception(f"Upload failed: {upload_res.status_code} - {upload_res.text}")

            storage_id = upload_res.json().get("storageId")
            if not storage_id:
                raise Exception("No storageId returned by Convex")

            logger.info(f"Successfully uploaded thumbnail: {storage_id}")
            
            return jsonify({
                "success": True,
                "storageId": storage_id,
                "dimensions": f"{new_width}x{new_height}",
                "fileSize": jpeg_size
            })

    except requests.RequestException as e:
        logger.error(f"Network error: {e}")
        return jsonify({
            "error": "Network error during processing",
            "details": str(e)
        }), 500
    except Exception as e:
        logger.error(f"Processing error: {e}")
        return jsonify({
            "error": "RAW to JPEG conversion failed",
            "details": str(e)
        }), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "rawpy-thumbnail-service",
        "version": "1.1.0",
        "features": ["rawpy", "PIL", "thumbnail-optimization"]
    })

# Error handler for large requests
@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({
        "error": "Request too large",
        "details": "File size exceeds maximum allowed"
    }), 413

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)