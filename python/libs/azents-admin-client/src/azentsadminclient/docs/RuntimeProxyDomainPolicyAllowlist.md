# RuntimeProxyDomainPolicyAllowlist

Explicit allowlist hostname authority with final denials.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**allowed_domains** | **List[str]** |  | 
**denied_domains** | **List[str]** |  | 
**mode** | **str** |  | 

## Example

```python
from azentsadminclient.models.runtime_proxy_domain_policy_allowlist import RuntimeProxyDomainPolicyAllowlist

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProxyDomainPolicyAllowlist from a JSON string
runtime_proxy_domain_policy_allowlist_instance = RuntimeProxyDomainPolicyAllowlist.from_json(json)
# print the JSON string representation of the object
print(RuntimeProxyDomainPolicyAllowlist.to_json())

# convert the object into a dict
runtime_proxy_domain_policy_allowlist_dict = runtime_proxy_domain_policy_allowlist_instance.to_dict()
# create an instance of RuntimeProxyDomainPolicyAllowlist from a dict
runtime_proxy_domain_policy_allowlist_from_dict = RuntimeProxyDomainPolicyAllowlist.from_dict(runtime_proxy_domain_policy_allowlist_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


