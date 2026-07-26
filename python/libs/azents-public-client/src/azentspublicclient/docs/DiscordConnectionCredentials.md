# DiscordConnectionCredentials

Validated secret payload for one Discord App connection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | **str** |  | [optional] [default to 'discord']
**bot_token** | **str** | Discord bot token | 

## Example

```python
from azentspublicclient.models.discord_connection_credentials import DiscordConnectionCredentials

# TODO update the JSON string below
json = "{}"
# create an instance of DiscordConnectionCredentials from a JSON string
discord_connection_credentials_instance = DiscordConnectionCredentials.from_json(json)
# print the JSON string representation of the object
print(DiscordConnectionCredentials.to_json())

# convert the object into a dict
discord_connection_credentials_dict = discord_connection_credentials_instance.to_dict()
# create an instance of DiscordConnectionCredentials from a dict
discord_connection_credentials_from_dict = DiscordConnectionCredentials.from_dict(discord_connection_credentials_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


