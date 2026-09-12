# RuntimeWebCloseRequest

Endpoint-revision-fenced exposure closure.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_endpoint_revision** | **int** |  | 
**operation_key** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_close_request import RuntimeWebCloseRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebCloseRequest from a JSON string
runtime_web_close_request_instance = RuntimeWebCloseRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebCloseRequest.to_json())

# convert the object into a dict
runtime_web_close_request_dict = runtime_web_close_request_instance.to_dict()
# create an instance of RuntimeWebCloseRequest from a dict
runtime_web_close_request_from_dict = RuntimeWebCloseRequest.from_dict(runtime_web_close_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


