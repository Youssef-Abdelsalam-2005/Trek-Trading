FROM python:3.12-slim

RUN pip install --no-cache-dir \
    pandas==2.2.* \
    numpy==1.26.* \
    scikit-learn==1.5.* \
    lightgbm==4.5.* \
    polars==1.* \
    vectorbt==0.26.*

RUN useradd -r -s /bin/false sandboxuser
USER sandboxuser

COPY runner.py /opt/runner.py

ENTRYPOINT ["python", "/opt/runner.py"]
