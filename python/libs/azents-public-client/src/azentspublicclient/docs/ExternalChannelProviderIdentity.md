# ExternalChannelProviderIdentity

Validated non-secret identity for one installed provider application.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**app_id** | **str** |  | 
**tenant_id** | **str** |  | 
**bot_user_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.external_channel_provider_identity import ExternalChannelProviderIdentity

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelProviderIdentity from a JSON string
external_channel_provider_identity_instance = ExternalChannelProviderIdentity.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelProviderIdentity.to_json())

# convert the object into a dict
external_channel_provider_identity_dict = external_channel_provider_identity_instance.to_dict()
# create an instance of ExternalChannelProviderIdentity from a dict
external_channel_provider_identity_from_dict = ExternalChannelProviderIdentity.from_dict(external_channel_provider_identity_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


