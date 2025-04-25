FROM python:3.10-slim

WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Run as non-root user for better security
RUN useradd -m botuser
USER botuser

# Command to run the application
CMD ["python", "main.py"]
