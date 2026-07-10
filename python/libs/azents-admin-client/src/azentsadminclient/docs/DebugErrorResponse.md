# DebugErrorResponse

Debug error response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**fired** | **bool** |  | 
**level** | **str** |  | 
**message** | **str** |  | 
**sentry_event_id** | **str** |  | 
**sentry** | [**SentryDiagnostics**](SentryDiagnostics.md) |  | 

## Example

```python
from azentsadminclient.models.debug_error_response import DebugErrorResponse

# TODO update the JSON string below
json = "{}"
# create an instance of DebugErrorResponse from a JSON string
debug_error_response_instance = DebugErrorResponse.from_json(json)
# print the JSON string representation of the object
print(DebugErrorResponse.to_json())

# convert the object into a dict
debug_error_response_dict = debug_error_response_instance.to_dict()
# create an instance of DebugErrorResponse from a dict
debug_error_response_from_dict = DebugErrorResponse.from_dict(debug_error_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


