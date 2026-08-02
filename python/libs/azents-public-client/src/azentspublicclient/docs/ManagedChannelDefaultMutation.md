# ManagedChannelDefaultMutation

Sanitized selected-Agent mutation result and terminal lifecycle impact.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**channel_default** | [**ManagedChannelDefault**](ManagedChannelDefault.md) |  | 
**changed** | **bool** |  | 
**invalidated_participation_setting_count** | **int** |  | 
**terminated_setup_claim_count** | **int** |  | 
**expired_interaction_count** | **int** |  | 
**disconnected_parent_binding_count** | **int** |  | 
**cleanup_delivery_count** | **int** |  | 

## Example

```python
from azentspublicclient.models.managed_channel_default_mutation import ManagedChannelDefaultMutation

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedChannelDefaultMutation from a JSON string
managed_channel_default_mutation_instance = ManagedChannelDefaultMutation.from_json(json)
# print the JSON string representation of the object
print(ManagedChannelDefaultMutation.to_json())

# convert the object into a dict
managed_channel_default_mutation_dict = managed_channel_default_mutation_instance.to_dict()
# create an instance of ManagedChannelDefaultMutation from a dict
managed_channel_default_mutation_from_dict = ManagedChannelDefaultMutation.from_dict(managed_channel_default_mutation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


