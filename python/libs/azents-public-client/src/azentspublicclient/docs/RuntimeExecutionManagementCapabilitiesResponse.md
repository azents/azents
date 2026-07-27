# RuntimeExecutionManagementCapabilitiesResponse

Safe server-owned policy management capability gate.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**docker** | **bool** |  | 
**storage_modes** | [**List[RuntimeExecutionStorageMode]**](RuntimeExecutionStorageMode.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_management_capabilities_response import RuntimeExecutionManagementCapabilitiesResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionManagementCapabilitiesResponse from a JSON string
runtime_execution_management_capabilities_response_instance = RuntimeExecutionManagementCapabilitiesResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionManagementCapabilitiesResponse.to_json())

# convert the object into a dict
runtime_execution_management_capabilities_response_dict = runtime_execution_management_capabilities_response_instance.to_dict()
# create an instance of RuntimeExecutionManagementCapabilitiesResponse from a dict
runtime_execution_management_capabilities_response_from_dict = RuntimeExecutionManagementCapabilitiesResponse.from_dict(runtime_execution_management_capabilities_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


