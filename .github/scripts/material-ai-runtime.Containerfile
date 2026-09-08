ARG BASE_IMAGE=deeplinkerp-custom:v16.23.0-latest
FROM ${BASE_IMAGE}

USER root
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      antiword \
      poppler-utils \
      tesseract-ocr \
      tesseract-ocr-chi-sim \
 && rm -rf /var/lib/apt/lists/*
USER frappe

