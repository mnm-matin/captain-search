FROM python:3.11-slim

WORKDIR /app

# Install uv for faster package installation
RUN pip install uv

# Copy project files
COPY pyproject.toml .
COPY README.md .
COPY src/ src/

# Install dependencies
RUN uv pip install --system -e .

# Create non-root user
RUN useradd -m -u 1000 appuser
USER appuser

# Default command - runs HTTP transport for remote MCP
ENTRYPOINT ["captain-search"]
CMD ["--transport", "http", "--port", "8000", "--host", "0.0.0.0"]
