@echo off
SET PROJECT_ID=lab7-490321
SET TAG=v2

echo Building REST Image v2...
docker build -f rest/Dockerfile-rest -t gcr.io/%PROJECT_ID%/demucs-rest:%TAG% rest/

echo Building Worker Image v2...
docker build -f worker/Dockerfile-worker -t gcr.io/%PROJECT_ID%/demucs-worker:%TAG% worker/

echo Pushing REST Image to GCR...
docker push gcr.io/%PROJECT_ID%/demucs-rest:%TAG%

echo Pushing Worker Image to GCR...
docker push gcr.io/%PROJECT_ID%/demucs-worker:%TAG%

echo Updating Kubernetes Deployments to use v2...
kubectl set image deployment/rest-deployment rest-server=gcr.io/%PROJECT_ID%/demucs-rest:%TAG%
kubectl set image deployment/worker-deployment worker-server=gcr.io/%PROJECT_ID%/demucs-worker:%TAG%

echo Deployment updated! Check pods with: kubectl get pods
pause
