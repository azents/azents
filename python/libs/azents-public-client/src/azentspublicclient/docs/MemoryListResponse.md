# MemoryListResponse

Memory list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[MemoryResponse]**](MemoryResponse.md) |  | 

## Example

```python
from azentspublicclient.models.memory_list_response import MemoryListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of MemoryListResponse from a JSON string
memory_list_response_instance = MemoryListResponse.from_json(json)
# print the JSON string representation of the object
print(MemoryListResponse.to_json())

# convert the object into a dict
memory_list_response_dict = memory_list_response_instance.to_dict()
# create an instance of MemoryListResponse from a dict
memory_list_response_from_dict = MemoryListResponse.from_dict(memory_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


