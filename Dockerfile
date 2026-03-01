# =============================================================================
# Dockerfile — AWS Lambda Container Image
# =============================================================================
# Base image: AWS-provided Lambda Python 3.12 runtime.
# This image includes the Lambda Runtime Interface Client (RIC) and is
# optimized for cold-start performance on AWS Lambda.
#
# Build:
#   docker build -t telecom-noc-agent .
#
# Test locally (requires Docker Desktop):
#   docker run -p 9000:8080 \
#     -e OPENAI_API_KEY=sk-... \
#     -e AWS_REGION=us-east-1 \
#     -e DYNAMODB_SOPS_TABLE=telecom-noc-sops \
#     -e DYNAMODB_TELEMETRY_TABLE=telecom-noc-telemetry \
#     -e AWS_ACCESS_KEY_ID=... \
#     -e AWS_SECRET_ACCESS_KEY=... \
#     telecom-noc-agent
#
# Invoke the local container:
#   curl -X POST http://localhost:9000/2015-03-31/functions/function/invocations \
#     -d '{"alarm_id": "ALARM-001", "error_message": ""}'
#
# Push to ECR (replace ACCOUNT_ID and REGION):
#   aws ecr get-login-password --region us-east-1 | \
#     docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
#   docker tag telecom-noc-agent:latest ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/telecom-noc-agent:latest
#   docker push ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/telecom-noc-agent:latest
# =============================================================================

FROM public.ecr.aws/lambda/python:3.12

# ---------------------------------------------------------------------------
# Install Python dependencies
# Note: --no-cache-dir reduces image size.
# ---------------------------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Copy application source code
# Only the files needed at runtime are included — scripts/, main.py,
# chroma_db/, and .venv/ are excluded via .dockerignore.
# ---------------------------------------------------------------------------
COPY src/              ${LAMBDA_TASK_ROOT}/src/
COPY data/             ${LAMBDA_TASK_ROOT}/data/
COPY lambda_handler.py ${LAMBDA_TASK_ROOT}/

# ---------------------------------------------------------------------------
# Lambda handler entrypoint
# Format: <module_name>.<function_name>
# ---------------------------------------------------------------------------
CMD ["lambda_handler.handler"]
