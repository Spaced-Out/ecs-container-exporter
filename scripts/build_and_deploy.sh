#!/bin/bash

set -e
echo "Pushing VISO Prometheus container from branch: ${GITHUB_REF}, sha: ${GITHUB_SHA}"

# map github ref to aws account name
if [[ ${GITHUB_REF} == 'refs/heads/development' ]]; then
  AWS_ACCOUNT="dev";
  GITHUB_BRANCH="development";
elif [[ ${GITHUB_REF} == 'refs/heads/main' ]]; then
  AWS_ACCOUNT="prod";
  GITHUB_BRANCH="latest";
else
  echo "Invalid deployment branch: ${GITHUB_REF}";
  exit 1;
fi

echo "Deploying image: ${IMAGE_NAME} to AWS account: ${AWS_ACCOUNT}"

ECR_ACCOUNT="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com"
ECR_REPO="${ECR_ACCOUNT}/${IMAGE_NAME}"

cd ..

temp_role=$(aws sts assume-role \
  --role-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:role/github-actions" \
  --role-session-name 'github-action-deploy-session')

export AWS_ACCESS_KEY_ID=$(echo $temp_role | jq -r .Credentials.AccessKeyId)
export AWS_SECRET_ACCESS_KEY=$(echo $temp_role | jq -r .Credentials.SecretAccessKey)
export AWS_SESSION_TOKEN=$(echo $temp_role | jq -r .Credentials.SessionToken)

docker build -t "${IMAGE_NAME}" -f ./Dockerfile .

docker tag "${IMAGE_NAME}" "${ECR_REPO}:${GITHUB_BRANCH}"
docker tag "${IMAGE_NAME}" "${ECR_REPO}:${GITHUB_SHA}"

ECR_TOKEN=$(aws ecr get-login-password)

docker login -u AWS -p "${ECR_TOKEN}" "${ECR_ACCOUNT}"

docker push "${ECR_REPO}:${GITHUB_BRANCH}"
docker push "${ECR_REPO}:${GITHUB_SHA}"
