# RuntimeProxyDomainPolicy


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**allowed_domains** | **List[str]** |  | 
**denied_domains** | **List[str]** |  | 
**mode** | **str** |  | 

## Example

```python
from azentsadminclient.models.runtime_proxy_domain_policy import RuntimeProxyDomainPolicy

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProxyDomainPolicy from a JSON string
runtime_proxy_domain_policy_instance = RuntimeProxyDomainPolicy.from_json(json)
# print the JSON string representation of the object
print(RuntimeProxyDomainPolicy.to_json())

# convert the object into a dict
runtime_proxy_domain_policy_dict = runtime_proxy_domain_policy_instance.to_dict()
# create an instance of RuntimeProxyDomainPolicy from a dict
runtime_proxy_domain_policy_from_dict = RuntimeProxyDomainPolicy.from_dict(runtime_proxy_domain_policy_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


