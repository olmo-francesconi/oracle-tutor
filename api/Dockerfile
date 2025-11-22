# Use a stable Python version
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
# build-essential and libpq-dev are often needed for python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file
COPY requirements.txt .

# Install PyTorch CPU-only version FIRST to avoid downloading the massive CUDA version
# Then install other dependencies
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY pyproject.toml .
COPY src/ src/
COPY tests/ tests/

# Install the package in editable mode
RUN pip install -e .

# Create the data directory
RUN mkdir -p data

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run the application
CMD ["uvicorn", "oracle_tutor_api.api:app", "--host", "0.0.0.0", "--port", "8000"]
