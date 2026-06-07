lint:
	ruff check claudemon/ tests/

test:
	pytest tests/ -v

coverage:
	pytest tests/ --cov=claudemon --cov-report=term-missing --cov-fail-under=80

install-pre-push:
	cp scripts/pre-push.sh .git/hooks/pre-push
	chmod +x .git/hooks/pre-push
