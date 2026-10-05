all: generate

.PHONY: all generate test

generate:
	uvx 'openapi-generator-cli[jdk4py]@7.17.0' generate -c config.yaml
	touch azentspublicclient/py.typed
	rm -rf src
	mkdir src
	mv azentspublicclient/ src/azentspublicclient/

test:
	PYTHONPATH=src:../azents-admin-client/src uv run python -m unittest discover -s ../../openapi-templates/tests
