#!/usr/bin/env bash
# Provisions the AWS side of peershare: an S3 bucket (private, presigned-URL
# access only, objects auto-expire after 1 day), an IAM role for Lambda,
# the Lambda function itself, and a public Function URL in front of it.
#
# Safe to re-run: each step checks whether its resource already exists
# before creating it, and the function code is always re-uploaded.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
BUCKET_NAME="${BUCKET_NAME:-peershare-files-$(date +%s)}"
FUNCTION_NAME="${FUNCTION_NAME:-peershare-backend}"
ROLE_NAME="${ROLE_NAME:-peershare-lambda-role}"

cd "$(dirname "$0")"

echo "Region:      $REGION"
echo "Bucket:      $BUCKET_NAME"
echo "Function:    $FUNCTION_NAME"
echo "IAM role:    $ROLE_NAME"
echo

echo "== S3 bucket =="
if aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$REGION" 2>/dev/null; then
  echo "Bucket already exists, skipping creation."
else
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
  echo "Created bucket $BUCKET_NAME."
fi

# CORS: lets the browser PUT directly to S3 (upload) and read the
# redirected GET response (download) cross-origin from the Vercel domain.
# The actual access control is the presigned URL signature, not CORS.
cat > /tmp/peershare-cors.json <<'EOF'
{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET", "PUT"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3000
    }
  ]
}
EOF
aws s3api put-bucket-cors --bucket "$BUCKET_NAME" --cors-configuration file:///tmp/peershare-cors.json --region "$REGION"

# Lifecycle: every object is deleted 1 day after upload, so storage cost
# stays near zero and shared links naturally stop working (mirrors the
# original project's "temporary share" intent).
cat > /tmp/peershare-lifecycle.json <<'EOF'
{
  "Rules": [
    {
      "ID": "expire-after-1-day",
      "Filter": { "Prefix": "" },
      "Status": "Enabled",
      "Expiration": { "Days": 1 }
    }
  ]
}
EOF
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET_NAME" \
  --lifecycle-configuration file:///tmp/peershare-lifecycle.json --region "$REGION"
echo "CORS + 1-day expiry lifecycle rule applied."
echo

echo "== IAM role =="
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "Role already exists, skipping creation."
else
  cat > /tmp/peershare-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Principal": { "Service": "lambda.amazonaws.com" }, "Action": "sts:AssumeRole" }
  ]
}
EOF
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document file:///tmp/peershare-trust-policy.json >/dev/null
  aws iam attach-role-policy --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  echo "Created role $ROLE_NAME, waiting for IAM propagation..."
  sleep 10
fi

cat > /tmp/peershare-s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
      "Resource": ["arn:aws:s3:::$BUCKET_NAME", "arn:aws:s3:::$BUCKET_NAME/*"]
    }
  ]
}
EOF
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name peershare-s3-access --policy-document file:///tmp/peershare-s3-policy.json
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
echo "Role ARN: $ROLE_ARN"
echo

echo "== Lambda function =="
rm -f function.zip
zip -j function.zip handler.py >/dev/null
echo "Packaged function.zip"

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FUNCTION_NAME" \
    --zip-file fileb://function.zip --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region "$REGION"
  aws lambda update-function-configuration --function-name "$FUNCTION_NAME" \
    --environment "Variables={BUCKET_NAME=$BUCKET_NAME}" --region "$REGION" >/dev/null
  echo "Updated existing function code + config."
else
  aws lambda create-function --function-name "$FUNCTION_NAME" \
    --runtime python3.12 --handler handler.lambda_handler \
    --role "$ROLE_ARN" --zip-file fileb://function.zip \
    --timeout 15 --memory-size 256 \
    --environment "Variables={BUCKET_NAME=$BUCKET_NAME}" \
    --region "$REGION" >/dev/null
  echo "Created function $FUNCTION_NAME."
fi

echo "== Function URL =="
if ! aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda create-function-url-config --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --cors '{"AllowOrigins":["*"],"AllowMethods":["GET","POST"],"AllowHeaders":["content-type"]}' \
    --region "$REGION" >/dev/null
  aws lambda add-permission --function-name "$FUNCTION_NAME" \
    --action lambda:InvokeFunctionUrl --principal "*" \
    --function-url-auth-type NONE --statement-id FunctionURLAllowPublicAccess \
    --region "$REGION" >/dev/null
  echo "Created public Function URL."
fi

FUNCTION_URL=$(aws lambda get-function-url-config --function-name "$FUNCTION_NAME" \
  --region "$REGION" --query 'FunctionUrl' --output text)
# Strip the trailing slash so it matches what next.config.js expects.
FUNCTION_URL="${FUNCTION_URL%/}"

echo
echo "=================================================================="
echo "Backend URL: $FUNCTION_URL"
echo
echo "Set this on the Vercel project (then redeploy the frontend):"
echo "  vercel env add BACKEND_URL production"
echo "  (paste: $FUNCTION_URL)"
echo "=================================================================="
