FROM python:3.12-slim-bookworm

WORKDIR /bot

RUN pip install poetry

COPY pyproject.toml poetry.lock ./

RUN poetry install --no-root

COPY . .

ENTRYPOINT ["poetry", "run", "python3"]
CMD ["main.py"]
