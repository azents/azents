# WorkspaceRuntimeNetworkRestrictionProxyRequired

Select proxy-required mode and restrictive destination policy.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | **str** |  | 
**allowed_cidrs** | **List[str]** |  | 
**denied_cidrs** | **List[str]** |  | 
**domain_policy** | [**RuntimeProxyDomainPolicy**](RuntimeProxyDomainPolicy.md) |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_network_restriction_proxy_required import WorkspaceRuntimeNetworkRestrictionProxyRequired

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeNetworkRestrictionProxyRequired from a JSON string
workspace_runtime_network_restriction_proxy_required_instance = WorkspaceRuntimeNetworkRestrictionProxyRequired.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeNetworkRestrictionProxyRequired.to_json())

# convert the object into a dict
workspace_runtime_network_restriction_proxy_required_dict = workspace_runtime_network_restriction_proxy_required_instance.to_dict()
# create an instance of WorkspaceRuntimeNetworkRestrictionProxyRequired from a dict
workspace_runtime_network_restriction_proxy_required_from_dict = WorkspaceRuntimeNetworkRestrictionProxyRequired.from_dict(workspace_runtime_network_restriction_proxy_required_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


