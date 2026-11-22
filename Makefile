.PHONY: install lint test up down init seed index bench experiments clean

install:
	pip install -e ".[dev,experiments]"

lint:
	ruff check .
	mypy

test:
	pytest -q

up:
	docker compose up --build -d

down:
	docker compose down

init:
	sorvia migrate
	sorvia bootstrap-roles
	sorvia seed --if-empty --demo-users
	sorvia index-schema

bench:
	python benchmark/run_text2sql.py

experiments:
	cd experiments && python rq1_retrieval.py && python rq3_guardrails.py && python rq4_index_advisor.py \
	  && python s1_index_types.py && python s2_isolation.py && python s3_partitioning_olap.py

clean:
	rm -rf build dist .mypy_cache .ruff_cache .pytest_cache experiments/results benchmark/results
