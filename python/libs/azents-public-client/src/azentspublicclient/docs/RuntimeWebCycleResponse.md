# RuntimeWebCycleResponse

Finite approved exposure cycle projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**request_id** | **str** |  | 
**duration_seconds** | **int** |  | 
**duration_configuration_revision** | **int** |  | 
**approved_at** | **datetime** |  | 
**expires_at** | **datetime** |  | 
**close_barrier** | **int** |  | 
**ended_at** | **datetime** |  | 
**end_reason** | [**RuntimeWebCycleEndReason**](RuntimeWebCycleEndReason.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_web_cycle_response import RuntimeWebCycleResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebCycleResponse from a JSON string
runtime_web_cycle_response_instance = RuntimeWebCycleResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebCycleResponse.to_json())

# convert the object into a dict
runtime_web_cycle_response_dict = runtime_web_cycle_response_instance.to_dict()
# create an instance of RuntimeWebCycleResponse from a dict
runtime_web_cycle_response_from_dict = RuntimeWebCycleResponse.from_dict(runtime_web_cycle_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


