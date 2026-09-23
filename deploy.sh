#!/usr/bin/env bash
# Section 38.1: the three-phase deploy. Terraform cannot create a Lambda from an image that
# is not in ECR yet, and ECR itself is Terraform-managed, so:
#   A. create the ECR repository only
#   B. build, tag and push the image
#   C. apply everything else
#
# Usage:   ./deploy.sh <image-tag>          e.g. ./deploy.sh v3-int8
#          AUTO_APPROVE=1 ./deploy.sh v4-int8   skip Terraform's confirmation prompts
set -euo pipefail

TAG=${1:-}
if [ -z "$TAG" ]; then
  echo "usage: ./deploy.sh <image-tag>   (a NEW tag for every change, e.g. v4-int8)" >&2
  exit 1
fi

# Trap 2 (section 4.4.1): an exported endpoint silently sends "real" commands to Floci.
if [ -n "${AWS_ENDPOINT_URL:-}" ]; then
  echo "AWS_ENDPOINT_URL is set ($AWS_ENDPOINT_URL). Unset it: this script targets real AWS." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF="terraform -chdir=$ROOT/terraform"
export AWS_PAGER=""
export AWS_REGION=${AWS_REGION:-us-east-1}
REPO_NAME=complaint-inference
LOCAL_IMAGE="$REPO_NAME:$TAG"
APPROVE=()
[ "${AUTO_APPROVE:-0}" = "1" ] && APPROVE=(-auto-approve)

echo "== Preflight (section 35)"
if ! IDENTITY=$(aws sts get-caller-identity --query '[Account, Arn]' --output text 2>&1); then
  echo "$IDENTITY" >&2
  echo "Not signed in to AWS. Run: aws login" >&2
  exit 1
fi
ACCOUNT_ID=$(echo "$IDENTITY" | cut -f1)
echo "   account  $ACCOUNT_ID"
echo "   identity $(echo "$IDENTITY" | cut -f2)"
echo "   region   $AWS_REGION"
docker info >/dev/null 2>&1 || { echo "Docker is not running." >&2; exit 1; }

$TF init -input=false >/dev/null

# The bucket was reserved by hand on Day 0 (section 4.9). If it still exists outside
# Terraform state, the apply fails with BucketAlreadyOwnedByYou half-way through.
BUCKET=$($TF console -var "image_tag=$TAG" <<<'var.bucket_name' 2>/dev/null | tr -d '"')
if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1 &&
  ! $TF state list 2>/dev/null | grep -q '^aws_s3_bucket.complaints$'; then
  cat >&2 <<EOF
Bucket $BUCKET exists but is not in Terraform state. Either:
  adopt it:  terraform -chdir=terraform import -var image_tag=$TAG aws_s3_bucket.complaints $BUCKET
  or delete: aws s3api delete-bucket --bucket $BUCKET   (only if empty)
EOF
  exit 1
fi

# Section 38.5: lost state means billable resources destroy can no longer see.
if [ -f "$ROOT/terraform/terraform.tfstate" ]; then
  cp "$ROOT/terraform/terraform.tfstate" "$ROOT/terraform/terraform.tfstate.bak.$(date +%s)"
fi

echo "== Phase A: ECR repository only"
# -target is normally a smell; this is the legitimate case: an external side effect
# (docker push) has to happen between two resources Terraform would create in one pass.
$TF apply "${APPROVE[@]}" -var "image_tag=$TAG" -target=aws_ecr_repository.inference
ECR_URI=$($TF output -raw ecr_repository_url)

echo "== Phase B: build, tag, push $TAG"
# The repository is IMMUTABLE; say so plainly rather than letting the push fail opaquely.
if aws ecr describe-images --repository-name "$REPO_NAME" --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
  echo "Tag $TAG is already in ECR and tags are immutable. Use a new tag, e.g. the next vN-int8." >&2
  exit 1
fi

# Always rebuild: layer caching makes this fast when only code changed, and it guarantees
# the pushed image matches the working tree (the v2-int8 image once shipped without the
# SQS branch, and nothing errored).
docker build --platform linux/amd64 -f "$ROOT/docker/inference/Dockerfile" -t "$LOCAL_IMAGE" "$ROOT"

aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "${ECR_URI%%/*}"
docker tag "$LOCAL_IMAGE" "$ECR_URI:$TAG"
docker push "$ECR_URI:$TAG"

echo "   verifying the push landed"
aws ecr describe-images --repository-name "$REPO_NAME" --image-ids "imageTag=$TAG" \
  --query 'imageDetails[0].[imageTags[0], imageSizeInBytes, imagePushedAt]' --output text

echo "== Phase C: everything else"
$TF apply "${APPROVE[@]}" -var "image_tag=$TAG"

INVOKE_URL=$($TF output -raw invoke_url)
KEY_ID=$($TF output -raw api_key_id)
cat <<EOF

Deployed $TAG.
  invoke URL  $INVOKE_URL
  API key id  $KEY_ID

Smoke test:
  API_KEY=\$(aws apigateway get-api-key --api-key $KEY_ID --include-value --query value --output text)
  curl -s -XPOST "$INVOKE_URL" -H "x-api-key: \$API_KEY" -H 'Content-Type: application/json' \\
    -d '{"text":"I found an error on my credit report and want it corrected."}'
EOF
