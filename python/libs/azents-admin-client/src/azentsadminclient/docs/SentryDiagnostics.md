# SentryDiagnostics

Sentry SDK diagnostics.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**initialized** | **bool** |  |
**dsn_configured** | **bool** |  |

## Example

```python
from azentsadminclient.models.sentry_diagnostics import SentryDiagnostics

# TODO update the JSON string below
json = "{}"
# create an instance of SentryDiagnostics from a JSON string
sentry_diagnostics_instance = SentryDiagnostics.from_json(json)
# print the JSON string representation of the object
print(SentryDiagnostics.to_json())

# convert the object into a dict
sentry_diagnostics_dict = sentry_diagnostics_instance.to_dict()
# create an instance of SentryDiagnostics from a dict
sentry_diagnostics_from_dict = SentryDiagnostics.from_dict(sentry_diagnostics_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
