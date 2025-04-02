# Use an official Python 3.11 runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependency file and version file first for layer caching
COPY requirements.txt VERSION ./

# Install Python dependencies
# Using --no-cache-dir to keep image size smaller
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
# Ensure all necessary .py files, .sh files, etc. are copied
COPY . .

# Create directories for logs and potential database mount point if needed
# These ensure the directories exist inside the container for mounting volumes
RUN mkdir logs

# Expose the port Streamlit runs on
EXPOSE 8501

# Set healthcheck for Streamlit
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

# Command to run the application
# Use the specific python script directly
# --server.enableCORS=false and --server.enableXsrfProtection=false might be needed
# depending on deployment, but omitted for basic local run.
CMD ["streamlit", "run", "gemini_local_chat.py", "--server.port=8501", "--server.address=0.0.0.0"]