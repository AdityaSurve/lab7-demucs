@echo off
SET PROJECT_ID=lab7-490321

echo Granting GKE nodes permission to read from the Registry...
:: The default compute service account needs the artifactregistry.reader role
call gcloud projects add-iam-policy-binding %PROJECT_ID% --member=serviceAccount:109294833359-compute@developer.gserviceaccount.com --role=roles/artifactregistry.reader

echo Restarting Kubernetes Pods so they can try pulling again...
call kubectl rollout restart deployment rest-deployment
call kubectl rollout restart deployment worker-deployment

echo Fix complete! Check pods with: kubectl get pods
pause
