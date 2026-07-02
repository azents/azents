# MemoryUpdateRequest

Memory update request, for partial updates.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Type | [optional] 
**name** | **str** | Memory identifier | [optional] 
**description** | **str** | One-line summary | [optional] 
**content** | **str** | Memory body | [optional] 

## Example

```python
from azentspublicclient.models.memory_update_request import MemoryUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of MemoryUpdateRequest from a JSON string
memory_update_request_instance = MemoryUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(MemoryUpdateRequest.to_json())

# convert the object into a dict
memory_update_request_dict = memory_update_request_instance.to_dict()
# create an instance of MemoryUpdateRequest from a dict
memory_update_request_from_dict = MemoryUpdateRequest.from_dict(memory_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


