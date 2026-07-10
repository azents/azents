# DebugExceptionResponse

Debug exception response. The actual response is 500.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**message** | **str** |  | 

## Example

```python
from azentsadminclient.models.debug_exception_response import DebugExceptionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of DebugExceptionResponse from a JSON string
debug_exception_response_instance = DebugExceptionResponse.from_json(json)
# print the JSON string representation of the object
print(DebugExceptionResponse.to_json())

# convert the object into a dict
debug_exception_response_dict = debug_exception_response_instance.to_dict()
# create an instance of DebugExceptionResponse from a dict
debug_exception_response_from_dict = DebugExceptionResponse.from_dict(debug_exception_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


