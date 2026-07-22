# ExternalChannelCredentialSnapshot

Redacted indication of which encrypted credential fields are present.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) | Credential provider | 
**configured_fields** | **List[str]** | Configured secret field names without secret values | 

## Example

```python
from azentspublicclient.models.external_channel_credential_snapshot import ExternalChannelCredentialSnapshot

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelCredentialSnapshot from a JSON string
external_channel_credential_snapshot_instance = ExternalChannelCredentialSnapshot.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelCredentialSnapshot.to_json())

# convert the object into a dict
external_channel_credential_snapshot_dict = external_channel_credential_snapshot_instance.to_dict()
# create an instance of ExternalChannelCredentialSnapshot from a dict
external_channel_credential_snapshot_from_dict = ExternalChannelCredentialSnapshot.from_dict(external_channel_credential_snapshot_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


