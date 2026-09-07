# DiscordUrlPreviewSuppressionRequest

Required full-value Discord automatic URL-preview request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**suppress_url_previews** | **bool** |  | 

## Example

```python
from azentspublicclient.models.discord_url_preview_suppression_request import DiscordUrlPreviewSuppressionRequest

# TODO update the JSON string below
json = "{}"
# create an instance of DiscordUrlPreviewSuppressionRequest from a JSON string
discord_url_preview_suppression_request_instance = DiscordUrlPreviewSuppressionRequest.from_json(json)
# print the JSON string representation of the object
print(DiscordUrlPreviewSuppressionRequest.to_json())

# convert the object into a dict
discord_url_preview_suppression_request_dict = discord_url_preview_suppression_request_instance.to_dict()
# create an instance of DiscordUrlPreviewSuppressionRequest from a dict
discord_url_preview_suppression_request_from_dict = DiscordUrlPreviewSuppressionRequest.from_dict(discord_url_preview_suppression_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


