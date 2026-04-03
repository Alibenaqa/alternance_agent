FROM mcr.microsoft.com/playwright/python:v1.51.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "main.py"]
