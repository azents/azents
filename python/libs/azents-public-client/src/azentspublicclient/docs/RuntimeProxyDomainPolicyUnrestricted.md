# RuntimeProxyDomainPolicyUnrestricted

Unrestricted hostname authority before final denials.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**allowed_domains** | **List[str]** |  | 
**denied_domains** | **List[str]** |  | 
**mode** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_proxy_domain_policy_unrestricted import RuntimeProxyDomainPolicyUnrestricted

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProxyDomainPolicyUnrestricted from a JSON string
runtime_proxy_domain_policy_unrestricted_instance = RuntimeProxyDomainPolicyUnrestricted.from_json(json)
# print the JSON string representation of the object
print(RuntimeProxyDomainPolicyUnrestricted.to_json())

# convert the object into a dict
runtime_proxy_domain_policy_unrestricted_dict = runtime_proxy_domain_policy_unrestricted_instance.to_dict()
# create an instance of RuntimeProxyDomainPolicyUnrestricted from a dict
runtime_proxy_domain_policy_unrestricted_from_dict = RuntimeProxyDomainPolicyUnrestricted.from_dict(runtime_proxy_domain_policy_unrestricted_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


