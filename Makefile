PYVERSION ?= 3.12.4
ENVNAME ?= cf-image-uploader

env: ## setup the dev virtual environment
	pyenv virtualenv ${PYVERSION} ${ENVNAME}
	ln -s "$(shell pyenv root)/versions/${PYVERSION}/envs/${ENVNAME}" .venv

rmenv: ## delete the dev virtual environment
	pyenv virtualenv-delete -f ${ENVNAME}
	rm .venv

fmt: ## format with black and isort
	black **/*.py ./*.py
	isort **/*.py ./*.py

test: ## run test suite
	python -m unittest discover -s tests

clean: ## remove build artifacts
	rm -rf build *.egg-info

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help