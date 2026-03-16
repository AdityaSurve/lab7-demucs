SET PROJECT_ID=lab7-490321

echo Enabling Container Registry API...
call gcloud services enable artifactregistry.googleapis.com

echo Configuring Docker Authentication...
call gcloud auth configure-docker gcr.io

echo Pushing REST Image to GCR...
docker push gcr.io/%PROJECT_ID%/demucs-rest:v1

echo Pushing Worker Image to GCR...
docker push gcr.io/%PROJECT_ID%/demucs-worker:v1

echo Restarting Kubernetes Pods...
call kubectl rollout restart deployment rest-deployment
call kubectl rollout restart deployment worker-deployment

echo Fix complete! Check pods with: kubectl get pods
pause
