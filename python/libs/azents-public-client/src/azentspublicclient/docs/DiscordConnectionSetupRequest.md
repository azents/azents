# DiscordConnectionSetupRequest

Secret-bearing Discord App setup input.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**app_id** | **str** |  | 
**configuration** | [**DiscordConnectionConfiguration**](DiscordConnectionConfiguration.md) |  | 
**credentials** | [**DiscordConnectionCredentials**](DiscordConnectionCredentials.md) |  | 

## Example

```python
from azentspublicclient.models.discord_connection_setup_request import DiscordConnectionSetupRequest

# TODO update the JSON string below
json = "{}"
# create an instance of DiscordConnectionSetupRequest from a JSON string
discord_connection_setup_request_instance = DiscordConnectionSetupRequest.from_json(json)
# print the JSON string representation of the object
print(DiscordConnectionSetupRequest.to_json())

# convert the object into a dict
discord_connection_setup_request_dict = discord_connection_setup_request_instance.to_dict()
# create an instance of DiscordConnectionSetupRequest from a dict
discord_connection_setup_request_from_dict = DiscordConnectionSetupRequest.from_dict(discord_connection_setup_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


