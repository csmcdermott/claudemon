venv := ".venv/bin"

# Create venv and install all dependencies (run once after cloning)
setup:
	python3 -m venv .venv
	{{venv}}/pip install --upgrade pip
	{{venv}}/pip install -e ".[dev]"

lint:
	{{venv}}/ruff check claudemon/ tests/

test:
	{{venv}}/pytest tests/ -v

coverage:
	{{venv}}/pytest tests/ --cov=claudemon --cov-report=term-missing --cov-fail-under=80

install-pre-push:
	cp scripts/pre-push.sh .git/hooks/pre-push
	chmod +x .git/hooks/pre-push

# Build claudemon.app bundle (output: dist/claudemon.app)
build:
	rm -rf build dist
	{{venv}}/python setup.py py2app

# Build and copy to /Applications (requires build first)
install-app: build
	rm -rf /Applications/claudemon.app
	cp -r dist/claudemon.app /Applications/claudemon.app
	@echo "Installed to /Applications/claudemon.app"
