FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
RUN useradd -r -u 10001 mock
USER mock
EXPOSE 8795
HEALTHCHECK --interval=5s --timeout=3s --retries=10 CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8795/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8795"]
