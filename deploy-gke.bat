@echo off
SET PROJECT_ID=lab7-490321

echo Building REST Image...
docker build -f rest/Dockerfile-rest -t gcr.io/%PROJECT_ID%/demucs-rest:v1 rest/

echo Building Worker Image...
docker build -f worker/Dockerfile-worker -t gcr.io/%PROJECT_ID%/demucs-worker:v1 worker/

echo Pushing REST Image to GCR...
docker push gcr.io/%PROJECT_ID%/demucs-rest:v1

echo Pushing Worker Image to GCR...
docker push gcr.io/%PROJECT_ID%/demucs-worker:v1

echo Applying Kubernetes Deployments...
powershell -Command "(gc rest\rest-app.yaml) -replace 'YOUR_PROJECT_ID_HERE', '%PROJECT_ID%' | Out-File -encoding ASCII rest\rest-app.yaml"
powershell -Command "(gc worker\worker-app.yaml) -replace 'YOUR_PROJECT_ID_HERE', '%PROJECT_ID%' | Out-File -encoding ASCII worker\worker-app.yaml"

kubectl apply -f rest\rest-app.yaml
kubectl apply -f worker\worker-app.yaml
kubectl apply -f logs\logs-deployment.yaml
kubectl apply -f minio\minio-external-service.yaml
kubectl apply -f redis\redis-deployment.yaml
kubectl apply -f redis\redis-service.yaml

echo Deployment submitted successfully!
echo You can check the ingress IP using: kubectl get ingress rest-ingress
pause
