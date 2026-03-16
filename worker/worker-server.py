import os
import sys
# Unbuffered so we see logs immediately in Kubernetes
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
print("Worker process starting...", flush=True)

import json
import time
import requests
import platform
import subprocess
import redis
from minio import Minio
from minio.error import S3Error

# Environment variables
# Kubernetes may inject REDIS_PORT=tcp://host:6379 when a service named "redis" exists.
def _redis_host_port():
    port_raw = os.environ.get('REDIS_DB_PORT') or os.environ.get('REDIS_PORT', '6379')
    if isinstance(port_raw, str) and '://' in port_raw:
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

# Connect to Redis (long timeouts so blpop doesn't drop during idle)
redisClient = redis.StrictRedis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    socket_connect_timeout=10,
    socket_timeout=None,
    decode_responses=False,
)

# Connect to Minio
minioClient = Minio(
    MINIO_HOST,
    access_key=MINIO_USER,
    secret_key=MINIO_PASS,
    secure=False
)

# Logging helpers
infoKey = f"{platform.node()}.worker.info"
debugKey = f"{platform.node()}.worker.debug"

def log_debug(message, key=debugKey):
    print("DEBUG:", message, file=sys.stdout)
    sys.stdout.flush()
    try:
        redisClient.lpush('logging', f"{key}:{message}")
    except:
        pass

def log_info(message, key=infoKey):
    print("INFO:", message, file=sys.stdout)
    sys.stdout.flush()
    try:
        redisClient.lpush('logging', f"{key}:{message}")
    except:
        pass

def ensure_buckets():
    try:
        if not minioClient.bucket_exists("queue"):
            minioClient.make_bucket("queue")
        if not minioClient.bucket_exists("output"):
            minioClient.make_bucket("output")
    except S3Error as err:
        log_info(f"Error checking/creating buckets: {err}")

ensure_buckets()

try:
    log_info("Worker started, waiting for jobs...")
except Exception:
    pass  # Redis may be briefly unavailable at startup

def run_worker_loop():
    print("Worker loop started, blocking on Redis BLPOP...", flush=True)
    while True:
        try:
            # Block and wait for a job from toWorker queue
            # blpop returns a tuple (b'toWorker', b'{"hash": "...", "callback": {...}}')
            work = redisClient.blpop("toWorker", timeout=0)

            if not work:
                continue

            queue_name, job_data_bytes = work
            job_data = json.loads(job_data_bytes.decode('utf-8'))

            songhash = job_data.get('hash')
            callback = job_data.get('callback')

            if not songhash:
                log_info("Received job without songhash, skipping.")
                continue

            log_info(f"Processing job for hash: {songhash}")

            # File paths
            input_dir = "/tmp/input"
            output_dir = "/tmp/output"
            os.makedirs(input_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)

            local_mp3_path = os.path.join(input_dir, f"{songhash}.mp3")

            # Download from Minio
            try:
                log_debug(f"Downloading {songhash}.mp3 from Minio queue bucket")
                minioClient.fget_object("queue", f"{songhash}.mp3", local_mp3_path)
            except S3Error as err:
                log_info(f"Failed to download {songhash}.mp3 from Minio: {err}")
                continue

            # Run Demucs
            # NOTE: DEMUCS execution consumes memory. We use os.system to invoke it.
            demucs_cmd = f"python3 -m demucs.separate -n mdx_extra_q --mp3 --out {output_dir} {local_mp3_path}"
            log_debug(f"Executing: {demucs_cmd}")

            exit_code = os.system(demucs_cmd)
            tracks_dir = os.path.join(output_dir, "mdx_extra_q", songhash)

            if exit_code != 0:
                log_info(f"Demucs processing failed for {songhash} with exit code {exit_code}")
            else:
                log_info(f"Demucs processing successful for {songhash}")
                tracks = ["bass.mp3", "drums.mp3", "other.mp3", "vocals.mp3"]
                for track in tracks:
                    track_path = os.path.join(tracks_dir, track)
                    if os.path.exists(track_path):
                        minio_object_name = f"{songhash}-{track}"
                        try:
                            log_debug(f"Uploading {minio_object_name} to Minio output bucket")
                            minioClient.fput_object("output", minio_object_name, track_path, content_type="audio/mpeg")
                        except S3Error as err:
                            log_info(f"Failed to upload {track} to Minio: {err}")
                    else:
                        log_info(f"Expected track {track} not found in {tracks_dir}")

            # Webhook Callback
            if callback and 'url' in callback:
                callback_url = callback['url']
                callback_data = callback.get('data', {})
                log_debug(f"Triggering callback to {callback_url}")
                try:
                    requests.post(callback_url, json=callback_data, timeout=5)
                    log_debug(f"Callback successful")
                except Exception as e:
                    log_info(f"Callback failed: {str(e)}")

            # Clean up local files
            try:
                if os.path.exists(local_mp3_path):
                    os.remove(local_mp3_path)
                if os.path.exists(tracks_dir):
                    for file_name in os.listdir(tracks_dir):
                        os.remove(os.path.join(tracks_dir, file_name))
                    os.rmdir(tracks_dir)
            except Exception as e:
                log_debug(f"Error during local cleanup: {str(e)}")

            log_info(f"Finished processing job for hash: {songhash}")

        except Exception as e:
            log_info(f"Exception in worker main loop: {str(e)}")
            time.sleep(5)  # Prevent tight loop on persistent error

if __name__ == "__main__":
    while True:
        try:
            run_worker_loop()
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as e:
            print(f"Worker loop exited unexpectedly: {e}", file=sys.stderr)
            sys.stderr.flush()
            time.sleep(5)
