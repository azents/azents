# RuntimeWebCreateRequest

Create one Agent-port service.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**port** | **int** |  | 
**label** | **str** |  | 
**selected_duration_seconds** | **int** |  | 
**turn_on** | **bool** |  | 
**operation_key** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_create_request import RuntimeWebCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebCreateRequest from a JSON string
runtime_web_create_request_instance = RuntimeWebCreateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebCreateRequest.to_json())

# convert the object into a dict
runtime_web_create_request_dict = runtime_web_create_request_instance.to_dict()
# create an instance of RuntimeWebCreateRequest from a dict
runtime_web_create_request_from_dict = RuntimeWebCreateRequest.from_dict(runtime_web_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


