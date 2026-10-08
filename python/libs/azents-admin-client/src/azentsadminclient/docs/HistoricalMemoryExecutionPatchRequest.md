# HistoricalMemoryExecutionPatchRequest

Optimistic update of the system-owned memory execution cutoffs.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**max_turns** | **int** |  | [optional] 
**timeout_seconds** | **int** |  | [optional] 

## Example

```python
from azentsadminclient.models.historical_memory_execution_patch_request import HistoricalMemoryExecutionPatchRequest

# TODO update the JSON string below
json = "{}"
# create an instance of HistoricalMemoryExecutionPatchRequest from a JSON string
historical_memory_execution_patch_request_instance = HistoricalMemoryExecutionPatchRequest.from_json(json)
# print the JSON string representation of the object
print(HistoricalMemoryExecutionPatchRequest.to_json())

# convert the object into a dict
historical_memory_execution_patch_request_dict = historical_memory_execution_patch_request_instance.to_dict()
# create an instance of HistoricalMemoryExecutionPatchRequest from a dict
historical_memory_execution_patch_request_from_dict = HistoricalMemoryExecutionPatchRequest.from_dict(historical_memory_execution_patch_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


