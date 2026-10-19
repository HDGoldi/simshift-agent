# Strands Decider 2B on CPU (linux/arm64) for ECS Fargate. Built by deploy/decider/build.sh, which stages the
# pinned strands-decider source (git archive, no .git) and both Hugging Face snapshots into the build context.
FROM python:3.13-slim

ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
COPY src /opt/strands-decider
# Versions match the local MLX/torch environment the published runs used.
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0+930e6d5d pip install /opt/strands-decider \
        transformers==5.20.1 peft==0.21.2 accelerate==1.15.0 huggingface_hub==2.2.0

# Adapter as a plain directory; the base model in Hub cache layout, resolved offline by its pinned commit.
COPY models/decider /models/decider
COPY models/hub /models/hf/hub
ENV HF_HOME=/models/hf HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4

EXPOSE 8099
CMD ["strands-decider", "serve", "/models/decider", "--model-name", "strands-decider-2B-qwen3.5-v1-2610", \
     "--device", "cpu", "--host", "0.0.0.0", "--port", "8099"]
