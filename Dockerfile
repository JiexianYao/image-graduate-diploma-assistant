FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/docs data/exam data/admin data/metadata

EXPOSE 8080

CMD ["gunicorn", "index:app", "--config", "gunicorn.conf.py"]
