# Python OpenAPI templates

Both Python clients use this shared template directory through the supported
`templateDir` generator configuration. The generator remains pinned to **7.17.0**
in their native Makefiles.

`python/model_generic.mustache` comes from the upstream 7.17.0 template:
https://github.com/OpenAPITools/openapi-generator/blob/v7.17.0/modules/openapi-generator/src/main/resources/python/model_generic.mustache

Upstream SHA-256: `c38f59b7c531e5fe970beb02903ca4c6a9d5c7dbe3a572552366c00f8acb353b`

The only customization filters the generated, nested-converted `from_dict`
mapping by keys present in the original input before Pydantic validation. This
preserves omission versus explicit null, leaves Pydantic responsible for required
fields and omitted defaults, and retains the upstream additional-property policy.
It does not replace nested conversion with direct validation of raw JSON.

Regenerate using `make generate` in each client directory. Run the shared
regressions using `make test` in either client directory. No API schema change is
needed, and generated models must not be edited by hand.
