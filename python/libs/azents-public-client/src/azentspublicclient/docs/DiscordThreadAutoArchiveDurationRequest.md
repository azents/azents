# DiscordThreadAutoArchiveDurationRequest

Required full-value Discord Thread automatic archive request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**thread_auto_archive_duration_minutes** | [**DiscordThreadAutoArchiveDurationMinutes**](DiscordThreadAutoArchiveDurationMinutes.md) |  | 

## Example

```python
from azentspublicclient.models.discord_thread_auto_archive_duration_request import DiscordThreadAutoArchiveDurationRequest

# TODO update the JSON string below
json = "{}"
# create an instance of DiscordThreadAutoArchiveDurationRequest from a JSON string
discord_thread_auto_archive_duration_request_instance = DiscordThreadAutoArchiveDurationRequest.from_json(json)
# print the JSON string representation of the object
print(DiscordThreadAutoArchiveDurationRequest.to_json())

# convert the object into a dict
discord_thread_auto_archive_duration_request_dict = discord_thread_auto_archive_duration_request_instance.to_dict()
# create an instance of DiscordThreadAutoArchiveDurationRequest from a dict
discord_thread_auto_archive_duration_request_from_dict = DiscordThreadAutoArchiveDurationRequest.from_dict(discord_thread_auto_archive_duration_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


