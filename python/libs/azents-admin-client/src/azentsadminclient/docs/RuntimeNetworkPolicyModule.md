# RuntimeNetworkPolicyModule

Typed customer-traffic network boundary.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**allowed_cidrs** | **List[str]** |  | [optional] [default to []]
**denied_cidrs** | **List[str]** |  | [optional] [default to []]

## Example

```python
from azentsadminclient.models.runtime_network_policy_module import RuntimeNetworkPolicyModule

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeNetworkPolicyModule from a JSON string
runtime_network_policy_module_instance = RuntimeNetworkPolicyModule.from_json(json)
# print the JSON string representation of the object
print(RuntimeNetworkPolicyModule.to_json())

# convert the object into a dict
runtime_network_policy_module_dict = runtime_network_policy_module_instance.to_dict()
# create an instance of RuntimeNetworkPolicyModule from a dict
runtime_network_policy_module_from_dict = RuntimeNetworkPolicyModule.from_dict(runtime_network_policy_module_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


