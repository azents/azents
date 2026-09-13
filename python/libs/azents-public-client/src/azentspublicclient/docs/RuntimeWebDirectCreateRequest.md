# RuntimeWebDirectCreateRequest

Explicit direct-create confirmation using current displayed duration.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**label** | **str** |  | 
**duration_seconds** | **int** |  | 
**duration_configuration_revision** | **int** |  | 
**operation_key** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_direct_create_request import RuntimeWebDirectCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebDirectCreateRequest from a JSON string
runtime_web_direct_create_request_instance = RuntimeWebDirectCreateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebDirectCreateRequest.to_json())

# convert the object into a dict
runtime_web_direct_create_request_dict = runtime_web_direct_create_request_instance.to_dict()
# create an instance of RuntimeWebDirectCreateRequest from a dict
runtime_web_direct_create_request_from_dict = RuntimeWebDirectCreateRequest.from_dict(runtime_web_direct_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


