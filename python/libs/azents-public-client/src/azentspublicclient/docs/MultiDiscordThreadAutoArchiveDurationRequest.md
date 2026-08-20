# MultiDiscordThreadAutoArchiveDurationRequest

Generation-fenced Discord Multi App Thread policy request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**thread_auto_archive_duration_minutes** | [**DiscordThreadAutoArchiveDurationMinutes**](DiscordThreadAutoArchiveDurationMinutes.md) |  | 
**expected_generation** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.multi_discord_thread_auto_archive_duration_request import MultiDiscordThreadAutoArchiveDurationRequest

# TODO update the JSON string below
json = "{}"
# create an instance of MultiDiscordThreadAutoArchiveDurationRequest from a JSON string
multi_discord_thread_auto_archive_duration_request_instance = MultiDiscordThreadAutoArchiveDurationRequest.from_json(json)
# print the JSON string representation of the object
print(MultiDiscordThreadAutoArchiveDurationRequest.to_json())

# convert the object into a dict
multi_discord_thread_auto_archive_duration_request_dict = multi_discord_thread_auto_archive_duration_request_instance.to_dict()
# create an instance of MultiDiscordThreadAutoArchiveDurationRequest from a dict
multi_discord_thread_auto_archive_duration_request_from_dict = MultiDiscordThreadAutoArchiveDurationRequest.from_dict(multi_discord_thread_auto_archive_duration_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


