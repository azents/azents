# DiscordConnectionConfiguration

Validated non-secret configuration for one Discord App connection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | **str** |  | [optional] [default to 'discord']
**target_guild_id** | **str** | Target Discord Guild snowflake | 

## Example

```python
from azentspublicclient.models.discord_connection_configuration import DiscordConnectionConfiguration

# TODO update the JSON string below
json = "{}"
# create an instance of DiscordConnectionConfiguration from a JSON string
discord_connection_configuration_instance = DiscordConnectionConfiguration.from_json(json)
# print the JSON string representation of the object
print(DiscordConnectionConfiguration.to_json())

# convert the object into a dict
discord_connection_configuration_dict = discord_connection_configuration_instance.to_dict()
# create an instance of DiscordConnectionConfiguration from a dict
discord_connection_configuration_from_dict = DiscordConnectionConfiguration.from_dict(discord_connection_configuration_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


