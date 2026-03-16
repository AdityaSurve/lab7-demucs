import os
import io
import json
import base64
import hashlib
import platform
import logging
from flask import Flask, request, jsonify, send_file, render_template, send_from_directory
import redis
from minio import Minio
from minio.error import S3Error

app = Flask(__name__)

# Environment variables
# Kubernetes may inject REDIS_PORT=tcp://host:6379 when a service named "redis" exists.
# Support both that and plain REDIS_HOST + REDIS_PORT (or REDIS_DB_PORT).
def _redis_host_port():
    port_raw = os.environ.get('REDIS_DB_PORT') or os.environ.get('REDIS_PORT', '6379')
    if isinstance(port_raw, str) and '://' in port_raw:
        # e.g. tcp://34.118.239.26:6379
        from urllib.parse import urlparse
        u = urlparse(port_raw)
        host = u.hostname or os.environ.get('REDIS_HOST', 'redis')
        port = u.port or 6379
        return host, port
    try:
        port = int(port_raw)
    except (ValueError, TypeError):
        port = 6379
    return os.environ.get('REDIS_HOST', 'redis'), port

REDIS_HOST, REDIS_PORT = _redis_host_port()

_minio_host = os.environ.get('MINIO_HOST', 'minio:9000')
MINIO_HOST = _minio_host if ':' in _minio_host else f'{_minio_host}:9000'
MINIO_USER = os.environ.get('MINIO_USER', 'rootuser')
MINIO_PASS = os.environ.get('MINIO_PASS', 'rootpass123')

# Connect to Redis
redisClient = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=0)

# Connect to Minio
minioClient = Minio(
    MINIO_HOST,
    access_key=MINIO_USER,
    secret_key=MINIO_PASS,
    secure=False
)

def ensure_buckets():
    try:
        if not minioClient.bucket_exists("queue"):
            minioClient.make_bucket("queue")
        if not minioClient.bucket_exists("output"):
            minioClient.make_bucket("output")
    except S3Error as err:
        print(f"Error checking/creating buckets: {err}")

# Ensure buckets exist on startup
ensure_buckets()

# Logging helpers
infoKey = f"{platform.node()}.rest.info"
debugKey = f"{platform.node()}.rest.debug"

def log_debug(message, key=debugKey):
    print("DEBUG:", message)
    redisClient.lpush('logging', f"{key}:{message}")

def log_info(message, key=infoKey):
    print("INFO:", message)
    redisClient.lpush('logging', f"{key}:{message}")

@app.route('/', methods=['GET'])
def hello():
    # Healthcheck / Extra Credit UI Serve
    # We will serve the static index.html or simple UI from here. 
    return send_file('index.html')

@app.route('/apiv1/separate', methods=['POST'])
def separate():
    """
    Accepts JSON body: {"mp3": <base64 encoded mp3>, "callback": {...}}
    """
    try:
        req_data = request.get_json()
        if not req_data or 'mp3' not in req_data:
            return jsonify({"error": "No mp3 data provided"}), 400

        mp3_b64 = req_data['mp3']
        callback = req_data.get('callback', {})

        # Decode base64
        mp3_bytes = base64.b64decode(mp3_b64)
        
        # Calculate hash (using md5 or sha256)
        songhash = hashlib.sha256(mp3_bytes).hexdigest()

        log_info(f"Received separation request for hash: {songhash}")

        # Upload to Minio "queue" bucket
        mp3_stream = io.BytesIO(mp3_bytes)
        minioClient.put_object(
            "queue", 
            f"{songhash}.mp3", 
            mp3_stream, 
            length=len(mp3_bytes),
            content_type="audio/mpeg"
        )
        log_debug(f"Uploaded {songhash}.mp3 to Minio queue bucket")

        # Create job payload
        job_data = {
            "hash": songhash,
            "callback": callback
        }
        
        # Enqueue job to Redis
        redisClient.lpush('toWorker', json.dumps(job_data))
        log_info(f"Enqueued job {songhash} to toWorker list")

        return jsonify({"hash": songhash, "reason": "Song enqueued for separation"}), 200

    except Exception as e:
        log_info(f"Error in /apiv1/separate: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/apiv1/queue', methods=['GET'])
def get_queue():
    """
    Returns a list of song hashes currently in the queue.
    """
    try:
        # Get all items from Redis list 'toWorker'
        items = redisClient.lrange('toWorker', 0, -1)
        queue_hashes = []
        for item in items:
            job_data = json.loads(item.decode('utf-8'))
            queue_hashes.append(job_data.get('hash'))
        
        return jsonify({"queue": queue_hashes}), 200
    except Exception as e:
        log_info(f"Error in /apiv1/queue: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/apiv1/track/<songhash>/<track_name>', methods=['GET'])
def get_track(songhash, track_name):
    """
    Retrieve track (base, vocals, drums, other).mp3
    """
    # map e.g base.mp3 -> bass.mp3 since demucs outputs bass instead of base usually, 
    # but handle based on actual object name
    object_name = f"{songhash}-{track_name}"
    
    try:
        # Check if object exists by getting stat
        minioClient.stat_object("output", object_name)
        
        # Get object
        response = minioClient.get_object("output", object_name)
        file_stream = io.BytesIO(response.read())
        response.close()
        response.release_conn()

        return send_file(
            file_stream, 
            mimetype="audio/mpeg", 
            as_attachment=True, 
            download_name=object_name
        )
    except S3Error as err:
        log_info(f"Track {object_name} not found or error: {err}")
        return jsonify({"error": "Track not found"}), 404
    except Exception as e:
        log_info(f"Error in get_track: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/apiv1/remove/<songhash>/<track_name>', methods=['GET', 'DELETE'])
def remove_track(songhash, track_name):
    """
    Deletes the track from Minio output bucket.
    """
    object_name = f"{songhash}-{track_name}"
    try:
        minioClient.remove_object("output", object_name)
        log_info(f"Removed track {object_name} from Minio output bucket")
        return jsonify({"message": f"Successfully removed {object_name}"}), 200
    except S3Error as err:
        log_info(f"Error removing track {object_name}: {err}")
        return jsonify({"error": "Failed to remove track"}), 500

if __name__ == '__main__':
    # Running on 0.0.0.0 to be externally visible in docker container
    app.run(host='0.0.0.0', port=5000)
