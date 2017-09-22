venv ?= .env
python_version ?= 3.3

pip := $(venv)/bin/pip
python := $(venv)/bin/python

remote_user ?= `whoami`
remote_host="$(remote_user)@rc.pdx.edu"


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

upload_dist: clean clean-build clean-dist
	$(venv)/bin/python setup.py bdist_wheel --universal
	@for archive in `ls dist`; do \
            scp dist/$${archive} $(remote_host):/tmp/; \
            ssh $(remote_host) chgrp arc /tmp/$${archive}; \
            ssh $(remote_host) sg arc -c "\"mv /tmp/$${archive} /vol/www/cdn/pypi/dist/\""; \
        done

.PHONY = init reinit clean clean-all clean-venv upload_dist
