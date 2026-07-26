# RuntimeExecutionNetworkModule

Nested-workload optional egress authority.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**module_id** | **str** |  | 
**version** | **int** |  | 
**mode** | [**RuntimeExecutionNetworkMode**](RuntimeExecutionNetworkMode.md) |  | 
**allowed_destinations** | **List[str]** |  | 
**denied_destinations** | **List[str]** |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_network_module import RuntimeExecutionNetworkModule

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionNetworkModule from a JSON string
runtime_execution_network_module_instance = RuntimeExecutionNetworkModule.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionNetworkModule.to_json())

# convert the object into a dict
runtime_execution_network_module_dict = runtime_execution_network_module_instance.to_dict()
# create an instance of RuntimeExecutionNetworkModule from a dict
runtime_execution_network_module_from_dict = RuntimeExecutionNetworkModule.from_dict(runtime_execution_network_module_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


