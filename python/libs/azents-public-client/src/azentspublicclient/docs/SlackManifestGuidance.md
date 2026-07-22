# SlackManifestGuidance


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | **str** |  | [optional] [default to 'slack']
**transport** | [**ExternalChannelTransport**](ExternalChannelTransport.md) |  | 
**bot_scopes** | **List[str]** |  | 
**event_subscriptions** | **List[str]** |  | 
**socket_mode_enabled** | **bool** |  | 
**app_token_scope** | **str** |  | 
**callback_url** | **str** |  | 
**manifest** | **Dict[str, object]** |  | 
**manifest_json** | **str** |  | 

## Example

```python
from azentspublicclient.models.slack_manifest_guidance import SlackManifestGuidance

# TODO update the JSON string below
json = "{}"
# create an instance of SlackManifestGuidance from a JSON string
slack_manifest_guidance_instance = SlackManifestGuidance.from_json(json)
# print the JSON string representation of the object
print(SlackManifestGuidance.to_json())

# convert the object into a dict
slack_manifest_guidance_dict = slack_manifest_guidance_instance.to_dict()
# create an instance of SlackManifestGuidance from a dict
slack_manifest_guidance_from_dict = SlackManifestGuidance.from_dict(slack_manifest_guidance_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


