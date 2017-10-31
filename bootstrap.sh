#!/bin/bash
set -e


python=`which python3`
venv=.env
if [ ! $? ]; then
    echo "Found no Python installation.";    
    exit 1;
else
  echo "Found Python ${python}";
fi

echo -e "-f https://pypi.research.pdx.edu/dist/\npsu.oit.arc.tasks>=1.1.0" > requirements.txt
${python} -m venv ${venv}
${venv}/bin/pip install -r requirements.txt
