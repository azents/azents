# HistoricalMemoryListResponse

Cursor-paginated Historical Memory settings response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[HistoricalMemoryResponse]**](HistoricalMemoryResponse.md) |  | 
**next_cursor** | **str** |  | 

## Example

```python
from azentspublicclient.models.historical_memory_list_response import HistoricalMemoryListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of HistoricalMemoryListResponse from a JSON string
historical_memory_list_response_instance = HistoricalMemoryListResponse.from_json(json)
# print the JSON string representation of the object
print(HistoricalMemoryListResponse.to_json())

# convert the object into a dict
historical_memory_list_response_dict = historical_memory_list_response_instance.to_dict()
# create an instance of HistoricalMemoryListResponse from a dict
historical_memory_list_response_from_dict = HistoricalMemoryListResponse.from_dict(historical_memory_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


