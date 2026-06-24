# SlashCommandListResponse

Slash command list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SlashCommandResponse]**](SlashCommandResponse.md) | Available slash command list |

## Example

```python
from azentspublicclient.models.slash_command_list_response import SlashCommandListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SlashCommandListResponse from a JSON string
slash_command_list_response_instance = SlashCommandListResponse.from_json(json)
# print the JSON string representation of the object
print(SlashCommandListResponse.to_json())

# convert the object into a dict
slash_command_list_response_dict = slash_command_list_response_instance.to_dict()
# create an instance of SlashCommandListResponse from a dict
slash_command_list_response_from_dict = SlashCommandListResponse.from_dict(slash_command_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
