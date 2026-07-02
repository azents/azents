# MemoryResponse

Memory response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**agent_id** | **str** |  | 
**user_id** | **str** |  | 
**scope** | [**MemoryScope**](MemoryScope.md) |  | 
**type** | **str** |  | 
**name** | **str** |  | 
**description** | **str** |  | 
**content** | **str** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.memory_response import MemoryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of MemoryResponse from a JSON string
memory_response_instance = MemoryResponse.from_json(json)
# print the JSON string representation of the object
print(MemoryResponse.to_json())

# convert the object into a dict
memory_response_dict = memory_response_instance.to_dict()
# create an instance of MemoryResponse from a dict
memory_response_from_dict = MemoryResponse.from_dict(memory_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


