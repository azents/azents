# MemoryCreateRequest

Memory creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**scope** | [**MemoryScope**](MemoryScope.md) | Scope | 
**type** | **str** | Type | 
**name** | **str** | Memory identifier | 
**description** | **str** | One-line summary | 
**content** | **str** | Memory body | 

## Example

```python
from azentspublicclient.models.memory_create_request import MemoryCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of MemoryCreateRequest from a JSON string
memory_create_request_instance = MemoryCreateRequest.from_json(json)
# print the JSON string representation of the object
print(MemoryCreateRequest.to_json())

# convert the object into a dict
memory_create_request_dict = memory_create_request_instance.to_dict()
# create an instance of MemoryCreateRequest from a dict
memory_create_request_from_dict = MemoryCreateRequest.from_dict(memory_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


