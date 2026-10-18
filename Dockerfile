FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY app /app/app
COPY configs /app/configs
COPY data/demo /app/data/demo

RUN pip install --no-cache-dir .

EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0"]

