# WorkspaceRuntimeNetworkRestrictionDirect

Retain direct mode while narrowing its CIDR authority.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | **str** |  | 
**allowed_cidrs** | **List[str]** |  | 
**denied_cidrs** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_network_restriction_direct import WorkspaceRuntimeNetworkRestrictionDirect

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeNetworkRestrictionDirect from a JSON string
workspace_runtime_network_restriction_direct_instance = WorkspaceRuntimeNetworkRestrictionDirect.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeNetworkRestrictionDirect.to_json())

# convert the object into a dict
workspace_runtime_network_restriction_direct_dict = workspace_runtime_network_restriction_direct_instance.to_dict()
# create an instance of WorkspaceRuntimeNetworkRestrictionDirect from a dict
workspace_runtime_network_restriction_direct_from_dict = WorkspaceRuntimeNetworkRestrictionDirect.from_dict(workspace_runtime_network_restriction_direct_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


