# SlackConnectionCredentials

Validated secret payload for one Slack App connection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | **str** |  | [optional] [default to 'slack']
**bot_token** | **str** | Slack bot user OAuth token | 
**signing_secret** | **str** | Slack request signing secret | 
**app_token** | **str** |  | 

## Example

```python
from azentspublicclient.models.slack_connection_credentials import SlackConnectionCredentials

# TODO update the JSON string below
json = "{}"
# create an instance of SlackConnectionCredentials from a JSON string
slack_connection_credentials_instance = SlackConnectionCredentials.from_json(json)
# print the JSON string representation of the object
print(SlackConnectionCredentials.to_json())

# convert the object into a dict
slack_connection_credentials_dict = slack_connection_credentials_instance.to_dict()
# create an instance of SlackConnectionCredentials from a dict
slack_connection_credentials_from_dict = SlackConnectionCredentials.from_dict(slack_connection_credentials_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


