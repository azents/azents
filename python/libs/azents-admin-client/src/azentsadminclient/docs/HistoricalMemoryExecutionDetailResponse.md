# HistoricalMemoryExecutionDetailResponse

Effective memory execution cutoffs with the admin mutation version.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**section** | **str** |  | 
**schema_version** | **int** |  | 
**admin_version** | **int** |  | 
**max_turns** | **int** |  | 
**timeout_seconds** | **int** |  | 

## Example

```python
from azentsadminclient.models.historical_memory_execution_detail_response import HistoricalMemoryExecutionDetailResponse

# TODO update the JSON string below
json = "{}"
# create an instance of HistoricalMemoryExecutionDetailResponse from a JSON string
historical_memory_execution_detail_response_instance = HistoricalMemoryExecutionDetailResponse.from_json(json)
# print the JSON string representation of the object
print(HistoricalMemoryExecutionDetailResponse.to_json())

# convert the object into a dict
historical_memory_execution_detail_response_dict = historical_memory_execution_detail_response_instance.to_dict()
# create an instance of HistoricalMemoryExecutionDetailResponse from a dict
historical_memory_execution_detail_response_from_dict = HistoricalMemoryExecutionDetailResponse.from_dict(historical_memory_execution_detail_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


