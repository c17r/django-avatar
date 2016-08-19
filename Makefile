export DJANGO_SETTINGS_MODULE=tests.settings
export PYTHONPATH=.

.PHONY: test

init:
	pip install --upgrade -r requirements.lock

requirements:
	pip install -r requirements.txt
	pip freeze > requirements.lock

test:
	flake8 avatar --ignore=E124,E501,E127,E128
	coverage run --source=avatar `which django-admin.py` test tests
	coverage report

publish: clean
	python setup.py sdist
	twine upload dist/*

clean:
	rm -vrf ./build ./dist ./*.egg-info ./avatars
	find . -name '*.pyc' -delete
	find . -name '*.tgz' -delete
