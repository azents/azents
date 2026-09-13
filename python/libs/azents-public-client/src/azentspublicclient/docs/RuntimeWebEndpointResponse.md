# RuntimeWebEndpointResponse

Stable Session-and-port endpoint projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**port** | **int** |  | 
**label** | **str** |  | 
**url** | **str** |  | 
**configuration_state** | **str** |  | 
**authority_revision** | **int** |  | 
**close_barrier** | **int** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_endpoint_response import RuntimeWebEndpointResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebEndpointResponse from a JSON string
runtime_web_endpoint_response_instance = RuntimeWebEndpointResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebEndpointResponse.to_json())

# convert the object into a dict
runtime_web_endpoint_response_dict = runtime_web_endpoint_response_instance.to_dict()
# create an instance of RuntimeWebEndpointResponse from a dict
runtime_web_endpoint_response_from_dict = RuntimeWebEndpointResponse.from_dict(runtime_web_endpoint_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


