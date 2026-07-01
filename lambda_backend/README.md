# peershare backend — AWS Lambda + S3 edition

A second, alternative backend for peershare (the original raw-socket version in
[`../p2p`](../p2p) still exists and still works for local/VM hosting — this is
for when you want the frontend on Vercel and a pay-per-request AWS backend
instead of an always-on VM).

## Why this looks different from the socket version

Lambda can't keep a `socket.listen()` open between requests, and each
invocation may run on a different machine with no shared memory or disk —
see the conversation that led here for the full reasoning. So the design
changes from "raw TCP P2P transfer" to "stateless signed-URL handoff":

- `POST /upload` — Lambda allocates an invite code and returns a **presigned
  S3 PUT URL**. The browser then uploads the file **directly to S3**,
  bypassing Lambda's ~6MB payload limit entirely.
- `GET /download/{code}` — Lambda finds the object stored under that code's
  S3 key prefix and **302-redirects** to a presigned GET URL. The browser
  downloads straight from S3.

The invite code doubles as the S3 key prefix (`{code}/{filename}`) — that's
the entire "database," and it's why this works statelessly across however
many parallel Lambda instances AWS decides to run.

The bucket stays **private** (default S3 "block public access" settings are
untouched). The only way to read or write an object is with a valid,
time-limited, cryptographically signed URL — there is no public bucket
policy.

## What you need

- An AWS account, with the **AWS CLI v2** installed and authenticated
  (`aws configure`, or `aws sso login`, or env vars — whatever you normally use).
  Run `aws sts get-caller-identity` to confirm it's working.
- `zip` available on your PATH (already present on macOS/Linux; on Windows,
  Git Bash includes it).
- IAM permissions to create S3 buckets, IAM roles, and Lambda functions.

## Deploy

```bash
cd lambda_backend
./deploy.sh
```

Optional environment variables (all have defaults):

| Variable | Default | Purpose |
|---|---|---|
| `AWS_REGION` | `us-east-1` | Region for everything |
| `BUCKET_NAME` | `peershare-files-<timestamp>` | Must be globally unique across all of S3 |
| `FUNCTION_NAME` | `peershare-backend` | Lambda function name |
| `ROLE_NAME` | `peershare-lambda-role` | IAM role name |

The script is safe to re-run — it skips creating resources that already
exist, and always re-uploads the latest `handler.py`.

At the end it prints a **Function URL**, e.g.:

```
https://abc123xyz.lambda-url.us-east-1.on.aws
```

## Wire it up to the Vercel frontend

```bash
cd ../ui
vercel env add BACKEND_URL production
# paste the Function URL printed above (no trailing slash)
vercel --prod
```

`next.config.js` already reads `BACKEND_URL` for its `/api/upload` and
`/api/download/:port` rewrites — no frontend code change needed for this step.

## Cost shape

- **Lambda**: first 1M requests + 400,000 GB-seconds/month are free; after
  that, fractions of a cent per request. This function does almost no work
  per request (it just calls S3 APIs and returns a URL), so compute time per
  invocation is tiny.
- **S3**: storage is billed per GB-month, but the 1-day lifecycle rule keeps
  total stored bytes near zero. PUT/GET requests are billed per-1000, also
  fractions of a cent.
- **Data transfer**: downloads egress from S3 directly (not through Lambda),
  billed at S3's standard data transfer rates, with a free monthly egress tier.

At hobby-project traffic levels, this should cost **$0/month**, sitting
entirely inside AWS's always-free tiers.

## Updating the function after editing `handler.py`

Just re-run `./deploy.sh` — it detects the function already exists and runs
`update-function-code` instead of `create-function`.

## Tearing it down

```bash
aws lambda delete-function --function-name peershare-backend --region us-east-1
aws iam delete-role-policy --role-name peershare-lambda-role --policy-name peershare-s3-access
aws iam detach-role-policy --role-name peershare-lambda-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name peershare-lambda-role
aws s3 rm s3://<your-bucket-name> --recursive
aws s3api delete-bucket --bucket <your-bucket-name> --region us-east-1
```
