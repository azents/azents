# WorkspaceRuntimeNetworkRestriction


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | **str** |  | 
**allowed_cidrs** | **List[str]** |  | 
**denied_cidrs** | **List[str]** |  | 
**domain_policy** | [**RuntimeProxyDomainPolicy**](RuntimeProxyDomainPolicy.md) |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_network_restriction import WorkspaceRuntimeNetworkRestriction

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeNetworkRestriction from a JSON string
workspace_runtime_network_restriction_instance = WorkspaceRuntimeNetworkRestriction.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeNetworkRestriction.to_json())

# convert the object into a dict
workspace_runtime_network_restriction_dict = workspace_runtime_network_restriction_instance.to_dict()
# create an instance of WorkspaceRuntimeNetworkRestriction from a dict
workspace_runtime_network_restriction_from_dict = WorkspaceRuntimeNetworkRestriction.from_dict(workspace_runtime_network_restriction_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


