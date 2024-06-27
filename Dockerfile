# Use a base image with 32-bit architecture
FROM i386/debian:bullseye-slim

# Set environment variables to non-interactive
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    direnv \
    default-jre \
    wget \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    llvm \
    libncurses5-dev \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libffi-dev \
    liblzma-dev \
    libgdbm-dev \
    libnss3-dev \
    libedit-dev \
    libdb5.3-dev \
 && rm -rf /var/lib/apt/lists/*

# Download and install Python 3.8
RUN wget https://www.python.org/ftp/python/3.8.0/Python-3.8.0.tgz \
    && tar -xf Python-3.8.0.tgz \
    && cd Python-3.8.0 \
    && ./configure --prefix=/usr/local --enable-optimizations \
    && make -j$(nproc) \
    && make altinstall \
    && rm -rf /Python-3.8.0.tgz /Python-3.8.0

# Set python3.8 as the default python
RUN ln -s /usr/local/bin/python3.8 /usr/bin/python

RUN apt-get update && apt-get install -y curl

# Install pip
RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py \
    && python3.8 get-pip.py \
    && rm get-pip.py
RUN pip install --upgrade pip

# Continue with your original setup
WORKDIR /app

COPY requirements.txt .

# Install pymupdf from the wheel file
#COPY PyMuPDF-1.24.6-cp38-none-musllinux_1_2_x86_64.whl .
#RUN pip install PyMuPDF-1.24.6-cp38-none-musllinux_1_2_x86_64.whl

RUN apt-get update \
    && apt-get -y install gcc unixodbc-dev \
    && pip install psycopg2 \
    && pip install -r requirements.txt

RUN pip install python-dotenv && apt-get -y install mupdf libmupdf-dev \
    && pip install PyMuPDF



# Copy the content of the local mpi_backend directory to the working directory
COPY . .

# Set the working directory to mpi_backend
WORKDIR /app/mpi_backend

ENV PYTHONPATH=../

# Ensure Java is in the PATH
ENV PATH="/usr/lib/jvm/java-11-openjdk-amd64/bin:$PATH"

# First do Alembic Migrations and then proceed towards Running Fast API
CMD ["bash", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]
