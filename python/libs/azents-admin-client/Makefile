all: generate

generate:
	uvx 'openapi-generator-cli[jdk4py]@7.17.0' generate -c config.yaml
	touch azentsadminclient/py.typed
	rm -rf src
	mkdir src
	mv azentsadminclient/ src/azentsadminclient/
