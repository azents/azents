# RuntimeProviderPolicyUpdateRequest

Mutable Provider administrative policy update.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**enabled** | **bool** |  | 
**lifecycle_state** | [**RuntimeProviderLifecycleState**](RuntimeProviderLifecycleState.md) |  | 
**availability_mode** | [**RuntimeProviderAvailabilityMode**](RuntimeProviderAvailabilityMode.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_policy_update_request import RuntimeProviderPolicyUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderPolicyUpdateRequest from a JSON string
runtime_provider_policy_update_request_instance = RuntimeProviderPolicyUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderPolicyUpdateRequest.to_json())

# convert the object into a dict
runtime_provider_policy_update_request_dict = runtime_provider_policy_update_request_instance.to_dict()
# create an instance of RuntimeProviderPolicyUpdateRequest from a dict
runtime_provider_policy_update_request_from_dict = RuntimeProviderPolicyUpdateRequest.from_dict(runtime_provider_policy_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


