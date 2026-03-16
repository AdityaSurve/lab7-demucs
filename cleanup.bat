@echo off
echo === Cleaning Kubernetes (default namespace) ===
kubectl delete ingress rest-ingress --ignore-not-found
kubectl delete deployment rest-deployment worker-deployment logs redis --ignore-not-found
kubectl delete service rest-service redis minio --ignore-not-found

echo.
echo === Removing local Docker images (demucs rest + worker, v1 and v2) ===
docker rmi gcr.io/lab7-490321/demucs-rest:v1 2>nul
docker rmi gcr.io/lab7-490321/demucs-rest:v2 2>nul
docker rmi gcr.io/lab7-490321/demucs-worker:v1 2>nul
docker rmi gcr.io/lab7-490321/demucs-worker:v2 2>nul
echo Local images removed (or were already missing).

echo.
echo === Optional: delete images from Google Container Registry ===
echo Run these if you also want to remove v1/v2 from GCR:
echo   gcloud container images delete gcr.io/lab7-490321/demucs-rest:v1 --force-delete-tags --quiet
echo   gcloud container images delete gcr.io/lab7-490321/demucs-rest:v2 --force-delete-tags --quiet
echo   gcloud container images delete gcr.io/lab7-490321/demucs-worker:v1 --force-delete-tags --quiet
echo   gcloud container images delete gcr.io/lab7-490321/demucs-worker:v2 --force-delete-tags --quiet
echo.
echo Done. You can redeploy from scratch (e.g. apply redis, minio, logs, rest, worker, then build and push new images).
pause
