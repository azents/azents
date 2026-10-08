# HistoricalMemoryResponse

Read-only Historical Memory settings response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**source_session_id** | **str** |  | 
**scope** | [**HistoricalMemorySettingsScope**](HistoricalMemorySettingsScope.md) |  | 
**source_title** | **str** |  | 
**source_activity_through** | **datetime** |  | 
**prepared_at** | **datetime** |  | 
**summary** | **str** |  | 
**source_path** | **str** |  | 

## Example

```python
from azentspublicclient.models.historical_memory_response import HistoricalMemoryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of HistoricalMemoryResponse from a JSON string
historical_memory_response_instance = HistoricalMemoryResponse.from_json(json)
# print the JSON string representation of the object
print(HistoricalMemoryResponse.to_json())

# convert the object into a dict
historical_memory_response_dict = historical_memory_response_instance.to_dict()
# create an instance of HistoricalMemoryResponse from a dict
historical_memory_response_from_dict = HistoricalMemoryResponse.from_dict(historical_memory_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


