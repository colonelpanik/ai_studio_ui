# Dockerfile
# Keep existing Dockerfile - ensure WORKDIR and COPY match new structure.
# Example structure (adapt if needed):
    FROM python:3.10-slim

    WORKDIR /app

    # Copy dependency file first for layer caching
    COPY requirements.txt .
    RUN pip install --no-cache-dir --upgrade pip && \
        pip install --no-cache-dir -r requirements.txt

    # Copy the entire application code from the 'app' directory
    COPY app/ /app/app/
    # Copy other necessary root files
    COPY VERSION README.md LICENSE.txt run.sh ./

    # Ensure run.sh is executable
    RUN chmod +x run.sh

    # Create logs directory and set permissions if needed
    RUN mkdir logs && chown -R nobody:nogroup /app
    USER nobody

    EXPOSE 8501

    HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

    # Default command using streamlit run on the new main script location
    CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]