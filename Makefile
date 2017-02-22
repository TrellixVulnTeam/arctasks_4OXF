venv ?= .env
python_version ?= 3.3

pip := $(venv)/bin/pip
python := $(venv)/bin/python

init: $(venv)
	$(pip) install -r requirements.txt
	$(python) -m unittest discover .

$(venv):
	virtualenv -p python$(python_version) $(venv)

reinit: clean-all init

clean:
	find . -name __pycache__ -type d -print0 | xargs -0 rm -r
clean-all: clean-build clean-dist clean-venv
clean-build:
	rm -rf build
clean-dist:
	rm -rf dist
clean-venv:
	rm -rf $(venv)

.PHONY = init reinit clean clean-all clean-venv
