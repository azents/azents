# RuntimeNetworkAccess


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mode** | **str** |  | 
**allowed_cidrs** | **List[str]** |  | 
**denied_cidrs** | **List[str]** |  | 
**domain_policy** | [**RuntimeProxyDomainPolicy**](RuntimeProxyDomainPolicy.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_network_access import RuntimeNetworkAccess

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeNetworkAccess from a JSON string
runtime_network_access_instance = RuntimeNetworkAccess.from_json(json)
# print the JSON string representation of the object
print(RuntimeNetworkAccess.to_json())

# convert the object into a dict
runtime_network_access_dict = runtime_network_access_instance.to_dict()
# create an instance of RuntimeNetworkAccess from a dict
runtime_network_access_from_dict = RuntimeNetworkAccess.from_dict(runtime_network_access_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


