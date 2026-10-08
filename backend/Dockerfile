FROM python:3.12.3

# Set the working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files to the working directory
COPY . .

# Expose port 8000 for the Django development server
EXPOSE 8000

# Run the Django development server on all network interfaces
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
