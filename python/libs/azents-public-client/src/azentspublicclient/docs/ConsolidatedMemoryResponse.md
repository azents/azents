# ConsolidatedMemoryResponse

Current integrated Memory settings overview for one exact scope.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**scope** | [**HistoricalMemorySettingsScope**](HistoricalMemorySettingsScope.md) |  | 
**markdown** | **str** |  | 
**published_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.consolidated_memory_response import ConsolidatedMemoryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ConsolidatedMemoryResponse from a JSON string
consolidated_memory_response_instance = ConsolidatedMemoryResponse.from_json(json)
# print the JSON string representation of the object
print(ConsolidatedMemoryResponse.to_json())

# convert the object into a dict
consolidated_memory_response_dict = consolidated_memory_response_instance.to_dict()
# create an instance of ConsolidatedMemoryResponse from a dict
consolidated_memory_response_from_dict = ConsolidatedMemoryResponse.from_dict(consolidated_memory_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


