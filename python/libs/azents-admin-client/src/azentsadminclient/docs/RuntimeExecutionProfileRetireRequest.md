# RuntimeExecutionProfileRetireRequest

Optimistic Profile retirement.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_profile_retire_request import RuntimeExecutionProfileRetireRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionProfileRetireRequest from a JSON string
runtime_execution_profile_retire_request_instance = RuntimeExecutionProfileRetireRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionProfileRetireRequest.to_json())

# convert the object into a dict
runtime_execution_profile_retire_request_dict = runtime_execution_profile_retire_request_instance.to_dict()
# create an instance of RuntimeExecutionProfileRetireRequest from a dict
runtime_execution_profile_retire_request_from_dict = RuntimeExecutionProfileRetireRequest.from_dict(runtime_execution_profile_retire_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


