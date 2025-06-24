PYVERSION ?= 3.13
ENVNAME ?= cf-image-uploader

env: ## setup the dev virtual environment
	pyenv virtualenv ${PYVERSION} ${ENVNAME}
	ln -s "$(shell pyenv root)/versions/${ENVNAME}" .venv

rmenv: ## delete the dev virtual environment
	pyenv virtualenv-delete -f ${ENVNAME}
	rm .venv

fmt: ## format with black and isort
	black cloudflare_image_uploader/*.py tests/*.py
	isort cloudflare_image_uploader/*.py tests/*.py

lint: ## lint the python files with pylint
	pylint --exit-zero cloudflare_image_uploader

test: ## run test suite
	python -m unittest discover -s tests

cov: ## get a coverage report of tests
	coverage run -m unittest discover -s tests
	coverage report

clean: ## remove build artifacts
	rm -rf cloudflare_image_uploader.egg-info build site .nox .coverage

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help