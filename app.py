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

def download_raw_file(raw_url, raw_path):
    """Download RAW file with size limits and error handling"""
    logger.info(f"Downloading RAW file from: {raw_url}")
    
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
    return file_size

def upload_to_convex(file_path, upload_url):
    """Upload file to Convex with error handling"""
    with open(file_path, "rb") as f:
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

    return storage_id

@app.route("/generate-thumbnail", methods=["POST"])
def generate_thumbnail():
    """Generate fast-loading, small thumbnail optimized for grid views"""
    data = request.get_json()
    raw_url = data.get("rawFileUrl")
    upload_url = data.get("uploadUrl")

    if not raw_url or not upload_url:
        return jsonify({"error": "Missing rawFileUrl or uploadUrl"}), 400

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "input.dng")
            jpeg_path = os.path.join(tmpdir, "thumbnail.jpg")

            # Download RAW file
            download_raw_file(raw_url, raw_path)

            # Convert RAW to RGB with thumbnail-optimized settings
            with rawpy.imread(raw_path) as raw:
                # Fast processing settings optimized for small thumbnails
                rgb = raw.postprocess(
                    use_camera_wb=True,           # Faster than auto WB
                    half_size=True,               # Process at half resolution for speed
                    dcb_iterations=1,             # Single iteration for speed
                    output_bps=8,                 # 8-bit output sufficient for thumbnails
                    no_auto_bright=True,          # Skip auto brightness for speed
                    noise_thr=100                 # Light noise reduction for cleaner thumbnails
                )
                
                # Convert to PIL Image
                img = Image.fromarray(rgb)
                
                # Small thumbnail size for fast loading
                original_width, original_height = img.size
                target_width, target_height = 400, 300  # Small for fast loading
                
                # Calculate scaling to fit within bounds
                width_ratio = target_width / original_width
                height_ratio = target_height / original_height
                scale_ratio = min(width_ratio, height_ratio)
                
                new_width = int(original_width * scale_ratio)
                new_height = int(original_height * scale_ratio)
                
                # Resize with good quality but optimized for speed
                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Save as JPEG optimized for small file size
                img_resized.save(
                    jpeg_path, 
                    'JPEG', 
                    quality=78,                   # Good quality but smaller file size
                    optimize=True,                # Enable JPEG optimization
                    progressive=True              # Progressive JPEG for web
                )

            # Get file size for logging
            jpeg_size = os.path.getsize(jpeg_path)
            logger.info(f"Generated thumbnail: {new_width}x{new_height}, {jpeg_size} bytes")

            # Upload to Convex
            storage_id = upload_to_convex(jpeg_path, upload_url)
            logger.info(f"Successfully uploaded thumbnail: {storage_id}")
            
            return jsonify({
                "success": True,
                "storageId": storage_id,
                "dimensions": f"{new_width}x{new_height}",
                "fileSize": jpeg_size,
                "type": "thumbnail"
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

@app.route("/generate-high-quality-jpeg", methods=["POST"])
def generate_high_quality_jpeg():
    """Generate high-quality JPEG for detailed viewing when user clicks on image"""
    data = request.get_json()
    raw_url = data.get("rawFileUrl")
    upload_url = data.get("uploadUrl")

    if not raw_url or not upload_url:
        return jsonify({"error": "Missing rawFileUrl or uploadUrl"}), 400

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, "input.dng")
            jpeg_path = os.path.join(tmpdir, "high_quality.jpg")

            # Download RAW file
            download_raw_file(raw_url, raw_path)

            # Convert RAW to RGB with maximum quality settings
            with rawpy.imread(raw_path) as raw:
                # Use high-quality processing settings for impressive results
                rgb = raw.postprocess(
                    use_auto_wb=True,             # Auto white balance for best color accuracy
                    half_size=False,              # Process at full resolution for maximum detail
                    dcb_iterations=2,             # More demosaicing iterations for better detail
                    output_bps=16,                # 16-bit processing for maximum color depth
                    noise_thr=None,               # Disable noise reduction to preserve detail
                    use_camera_wb=False,          # Use auto WB for better results
                    no_auto_bright=False,         # Allow auto brightness adjustment
                    exp_shift=1.0,                # Slight exposure boost
                    gamma=(2.222, 4.5),           # Standard gamma for web display
                    bright=1.0,                   # Standard brightness
                    highlight_mode=0,             # Clip highlights (preserves detail)
                    fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off  # Preserve fine detail
                )
                
                # Convert 16-bit to 8-bit for PIL processing
                if rgb.dtype == 'uint16':
                    rgb = (rgb / 256).astype('uint8')
                
                # Convert to PIL Image for resizing
                img = Image.fromarray(rgb)
                
                # Calculate high-resolution output size maintaining aspect ratio
                original_width, original_height = img.size
                target_width, target_height = 1920, 1440  # High resolution for impressive quality
                
                # Calculate scaling to fit within bounds
                width_ratio = target_width / original_width
                height_ratio = target_height / original_height
                scale_ratio = min(width_ratio, height_ratio)
                
                new_width = int(original_width * scale_ratio)
                new_height = int(original_height * scale_ratio)
                
                # Resize with highest quality resampling
                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Save as JPEG with maximum quality settings
                img_resized.save(
                    jpeg_path, 
                    'JPEG', 
                    quality=95,                   # Very high quality for impressive results
                    optimize=True,                # Enable JPEG optimization
                    progressive=True,             # Progressive JPEG for web
                    subsampling=0                 # No chroma subsampling for best quality
                )

            # Get file size for logging
            jpeg_size = os.path.getsize(jpeg_path)
            logger.info(f"Generated high-quality JPEG: {new_width}x{new_height}, {jpeg_size} bytes")

            # Upload to Convex
            storage_id = upload_to_convex(jpeg_path, upload_url)
            logger.info(f"Successfully uploaded high-quality JPEG: {storage_id}")
            
            return jsonify({
                "success": True,
                "storageId": storage_id,
                "dimensions": f"{new_width}x{new_height}",
                "fileSize": jpeg_size,
                "type": "high_quality"
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
        "service": "rawpy-high-quality-jpeg-service",
        "version": "1.2.0",
        "features": ["rawpy", "PIL", "high-quality-jpeg", "16-bit-processing"]
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