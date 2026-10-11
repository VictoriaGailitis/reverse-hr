# Provisioning artifact for a dedicated linux/amd64 executor; not a platform service.
# Export and pin the reviewed rootfs before enabling isolated probes.
FROM python:3.12.12-slim
RUN mkdir -p /runner /workspace /tmp
COPY src/reverse_hr/services/code_runner/sandbox_guest.py /runner/guest.py
