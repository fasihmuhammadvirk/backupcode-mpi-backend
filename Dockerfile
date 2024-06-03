FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    direnv \
    default-jre \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN apt-get update \
    && apt-get -y install gcc \
    && pip install psycopg2 \
    && pip install -r requirements.txt

RUN pip install -U python-dotenv

# Copy the content of the local mpi_backend directory to the working directory
COPY . .

# Set the working directory to mpi_backend
WORKDIR /app/mpi_backend

ENV PYTHONPATH=../

# Ensure Java is in the PATH
ENV PATH="/usr/lib/jvm/java-11-openjdk-amd64/bin:$PATH"

# First do Alembic Migrations and then proceed towards Running Fast API
CMD ["bash", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
