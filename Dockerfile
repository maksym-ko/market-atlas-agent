FROM python:3.12-slim
RUN pip install --no-cache-dir "uv>=0.9,<1"
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never HOST=0.0.0.0
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN useradd --create-home app && chown -R app /app/data
USER app
EXPOSE 8080
CMD ["uv", "run", "--no-dev", "python", "-m", "app.ui"]
