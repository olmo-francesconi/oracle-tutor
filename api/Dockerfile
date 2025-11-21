# Use an official Python runtime as a parent image
FROM python:3.14-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# We install build-essential to ensure we can build dependencies if needed
RUN apt-get update && apt-get install -y build-essential && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy the rest of the application code
COPY pyproject.toml .
COPY src/ src/

# Install the package in editable mode (as defined in requirements.txt)
RUN pip install -e .

# Create the data directory
RUN mkdir -p data

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run the application
CMD ["uvicorn", "manaseek_api.api:app", "--host", "0.0.0.0", "--port", "8000"]
