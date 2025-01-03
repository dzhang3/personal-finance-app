FROM python:3.12.3

# Set the working directory
WORKDIR /app

# Copy application files to the working directory
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port 8000 for the Django development server
EXPOSE 8000

# Run the Django development server on all network interfaces
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
