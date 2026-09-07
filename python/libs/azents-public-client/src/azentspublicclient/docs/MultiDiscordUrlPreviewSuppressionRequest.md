# MultiDiscordUrlPreviewSuppressionRequest

Generation-fenced Discord Multi App URL-preview policy request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**suppress_url_previews** | **bool** |  | 
**expected_generation** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.multi_discord_url_preview_suppression_request import MultiDiscordUrlPreviewSuppressionRequest

# TODO update the JSON string below
json = "{}"
# create an instance of MultiDiscordUrlPreviewSuppressionRequest from a JSON string
multi_discord_url_preview_suppression_request_instance = MultiDiscordUrlPreviewSuppressionRequest.from_json(json)
# print the JSON string representation of the object
print(MultiDiscordUrlPreviewSuppressionRequest.to_json())

# convert the object into a dict
multi_discord_url_preview_suppression_request_dict = multi_discord_url_preview_suppression_request_instance.to_dict()
# create an instance of MultiDiscordUrlPreviewSuppressionRequest from a dict
multi_discord_url_preview_suppression_request_from_dict = MultiDiscordUrlPreviewSuppressionRequest.from_dict(multi_discord_url_preview_suppression_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


