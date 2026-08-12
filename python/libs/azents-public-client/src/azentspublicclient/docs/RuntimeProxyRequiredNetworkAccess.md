# RuntimeProxyRequiredNetworkAccess

Inspected HTTP proxy authority within CIDR and domain boundaries.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | **str** |  | 
**allowed_cidrs** | **List[str]** |  | 
**denied_cidrs** | **List[str]** |  | 
**domain_policy** | [**RuntimeProxyDomainPolicy**](RuntimeProxyDomainPolicy.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_proxy_required_network_access import RuntimeProxyRequiredNetworkAccess

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProxyRequiredNetworkAccess from a JSON string
runtime_proxy_required_network_access_instance = RuntimeProxyRequiredNetworkAccess.from_json(json)
# print the JSON string representation of the object
print(RuntimeProxyRequiredNetworkAccess.to_json())

# convert the object into a dict
runtime_proxy_required_network_access_dict = runtime_proxy_required_network_access_instance.to_dict()
# create an instance of RuntimeProxyRequiredNetworkAccess from a dict
runtime_proxy_required_network_access_from_dict = RuntimeProxyRequiredNetworkAccess.from_dict(runtime_proxy_required_network_access_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


