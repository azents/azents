# SlashCommandResponse

Slash command response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** | Command name without leading slash |
**description** | **str** | Command description |

## Example

```python
from azentspublicclient.models.slash_command_response import SlashCommandResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SlashCommandResponse from a JSON string
slash_command_response_instance = SlashCommandResponse.from_json(json)
# print the JSON string representation of the object
print(SlashCommandResponse.to_json())

# convert the object into a dict
slash_command_response_dict = slash_command_response_instance.to_dict()
# create an instance of SlashCommandResponse from a dict
slash_command_response_from_dict = SlashCommandResponse.from_dict(slash_command_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


