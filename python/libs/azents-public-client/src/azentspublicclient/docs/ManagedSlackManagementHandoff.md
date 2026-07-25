# ManagedSlackManagementHandoff

Authenticated resolution of an opaque Slack management callback.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**interaction_id** | **str** |  | 
**connection_id** | **str** |  | 
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**provider_app_id** | **str** |  | 
**provider_channel_id** | **str** |  | 
**provider_thread_id** | **str** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.managed_slack_management_handoff import ManagedSlackManagementHandoff

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedSlackManagementHandoff from a JSON string
managed_slack_management_handoff_instance = ManagedSlackManagementHandoff.from_json(json)
# print the JSON string representation of the object
print(ManagedSlackManagementHandoff.to_json())

# convert the object into a dict
managed_slack_management_handoff_dict = managed_slack_management_handoff_instance.to_dict()
# create an instance of ManagedSlackManagementHandoff from a dict
managed_slack_management_handoff_from_dict = ManagedSlackManagementHandoff.from_dict(managed_slack_management_handoff_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


